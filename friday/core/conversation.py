"""
Conversation Manager and Context for F.R.I.D.A.Y. v2.

Owns session state, conversation context, pending confirmations,
system command handling, and tool execution dispatch.
"""
from dataclasses import dataclass, field
from typing import Optional
import re
import time

from friday.core.state import ConversationState, StateMachine
from friday.core.session import ConversationSession
from friday.intent.models import Action, Intent
from friday.intent.router import route
from friday.intent.normalizer import normalize, normalize_app_aliases
from friday.intent.classifier import RequestClass, classify, log_class
from friday.core.natural_conversation import NaturalConversationRouter
from friday.safety.validator import validate, Policy
from friday.safety.confirmation import parse_confirmation_response, format_confirmation_prompt
from friday.tools import registry
from friday.utils.logger import get_logger

from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.goal_models import GoalContext, GoalState
from friday.planning.planner import parse_plan
from friday.planning.executor import execute_plan_step
from friday.planning.plan_validator import validate_plan
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.reasoning.interface import Reasoner
from friday.reasoning.local_reasoner import OllamaReasoner
from friday.reasoning.gating import should_call_reasoner

logger = get_logger(__name__)

_HELP_TEXT = (
    "I can open applications and websites, search the web, find files, "
    "open folders, and tell you the time."
)

# Surrogate permissions if the caller supplied none — same set the planner used.
_DEFAULT_PERMS = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}

_REASONER_CONF = 0.9
_ASSISTANT_NAME = "friday"

# Deterministic exit / shutdown utterances. These are matched BEFORE any
# classifier or reasoner so "bye" is always an instant, no-LLM shutdown (P1).
_EXIT_UTTERANCES = frozenset({
    "stop", "shut down", "shutdown", "exit", "quit", "goodbye", "good bye",
    "bye", "stop friday", "see you", "thats all", "that's all",
})

# Natural Conversation Layer never touches these request classes: they are
# resolved further down the pipeline (commands, tools, anaphora, follow-ups,
# screen queries and the deterministic session-exit path).
_NATURAL_CONVERSATION_SKIP_CLASSES = frozenset({
    RequestClass.EXIT,
    RequestClass.COMMAND,
    RequestClass.TOOL_REQUEST,
    RequestClass.CONTEXT_REFERENCE,
    RequestClass.FOLLOW_UP,
    RequestClass.SCREEN_QUESTION,
})

# Command-like phrasing that gates app-alias expansion. Aliases exist to repair
# STT mishearings of application names inside actionable commands ("open grom" ->
# "open chrome"); they must never rewrite arbitrary chat words (P8).
_COMMAND_LIKE = re.compile(
    r"\b(open|launch|start|run|close|quit|exit|kill|search|look\s+up|google|"
    r"play|watch|find|read|go\s+to|visit|navigate|set|pause|resume|remember|"
    r"recall|forget|show|turn\s+on|turn\s+off|enable|disable|can\s+you|"
    r"could\s+you|please|volume|mute|unmute)\b",
    re.IGNORECASE,
)

# Current-information phrasing ("what is the latest news about X"). These must be
# routed to the LIVE WEB search tool deterministically, never to the local
# knowledge LLM (P5).
_LIVE_WEB_PREFIX = re.compile(
    r"^(?:what(?:'?s|\s+is|\s+are)\s+)(?:the\s+)?"
    r"(?:latest|breaking|most\s+recent|recent|current|today(?:'?s)?|tonight|"
    r"this\s+week|updates?)\s*(?:news)?"
    r"(?:\s+(?:about|on|in|for|across|regarding|of))?\s*(.+?)\s*$",
    re.IGNORECASE,
)

# Queries that look like live-info requests but are really about Friday's own
# codebase — these must stay on the knowledge/chat path.
_LIVE_WEB_LOCAL_FORBIDDEN = re.compile(
    r"\b(architecture|codebase|project|backend|frontend|stt|tts|rag|whisper|"
    r"piper|kokoro|reasoner|model|config|version of the|deployment)\b",
    re.IGNORECASE,
)

_CONV_FOLLOWUP_START = re.compile(
    r"^(why|how|what|what about|and|but|so|then|which|who|when|where)\b", re.I
)
_CONV_PRONOUN_RE = re.compile(r"\b(it|its|this|that|them|they)\b", re.I)

# Mirrors friday/rag/query_analyzer.py entity patterns (kept local to avoid
# coupling / import cycles; query_analyzer itself must not be modified).
_CONV_ENTITY_PATTERNS = {
    "authentication": r"\bauth\w*|\bjwt\b|\b(login|log\s*in|sign\s*in)\b",
    "database": r"\b(db|database|sqlite|mysql|postgres\w*|mongodb|schema|table)\b",
    "api": r"\bapi\b|\bendpoint\b|\brest\b|\bcrud\b",
    "voice": r"\b(voice|speech|stt|tts|audio|microphone|whisper|vad|piper|kokoro)\b",
    "reasoning": r"\b(reasoning|llm|llama|ollama|bonsai|model|gguf)\b",
    "embedding": r"\b(embedding|vector|semantic|retriev)\w*",
    "deployment": r"\b(deploy|server|docker|container|cloud|hosting|local)\b",
    "frontend": r"\b(frontend|ui|web app|dashboard|react|interface)\b",
    "backend": r"\b(backend|server[- ]side|node|flask|django|fastapi)\b",
}

# ----------------------------------------------------------------------
# Conversational reference resolution (context-window references).
# Deterministic, no model calls. Resolution status strings are plain
# strings so downstream code can branch without importing an enum.
# ----------------------------------------------------------------------
_REF_STATUS_NOT_NEEDED = "not_needed"
_REF_STATUS_RESOLVED = "resolved"
_REF_STATUS_AMBIGUOUS = "ambiguous"
_REF_STATUS_UNRESOLVED = "unresolved"

_MALE_PRONOUNS = re.compile(r"\b(he|him|his)\b", re.I)
_FEMALE_PRONOUNS = re.compile(r"\b(she|her)\b", re.I)
_GROUP_PRONOUNS = re.compile(r"\b(they|them|their)\b", re.I)
_ENTITY_PRONOUNS = re.compile(r"\b(it|its)\b", re.I)
_DEMONSTRATIVES = re.compile(r"\b(this|that|these|those)\b", re.I)
_PLACE_DEICTICS = re.compile(r"\b(here|there)\b", re.I)

# Which-word structures that introduce a question about a referent.
_WHO_QUESTION = re.compile(r"\bwho\s+(?:is|was|are|were)\b", re.I)
_WHICH_QUESTION = re.compile(r"\bwhich\b", re.I)

# Elliptical follow-ups that need the focus entity injected.
_TELL_MORE = re.compile(r"^(?:tell\s+me\s+more|go\s+on|continue|elaborate|expand)\b(.*)$", re.I)
_WHY_FOLLOWUP = re.compile(r"^(?:why|how\s+so|how\s+come|what\s+happened\s+next|and\s+then|then\s+what|why\s+is\s+that|why\s+is\s+this)\s*\??$", re.I)
_WHAT_ABOUT = re.compile(r"\bwhat\s+about\s+(.+?)\s*\??$", re.I)

# Detection of a brand-new explicit entity so we don't steal a tool command.
_IMPL_VERB = re.compile(
    r"\b(open|close|play|pause|stop|launch|start|run|quit|kill|search\s+for|"
    r"find|read|go\s+to|visit|remind)\b", re.I,
)

_TITLE_NAME = re.compile(r"\b(?:[A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,}){0,3}|[A-Z]{2,}[A-Za-z]*)\b")
_TITLE_OR_NAME = re.compile(
    r"\b([A-Z][a-z]{1,}(?:[ '’-][A-Z][a-z]*)*)\b",
)

# Same-turn topic repetition: a clause that *introduces* a topic by naming it
# ("what is node man", "like node man", "define node man"). Section 17 case:
# "can you tell me about it? freddened like node man. what is node man?
#  what's the purpose of using it?" - the trailing "it" belongs to the phrase
# named twice INSIDE the same utterance, not to whatever the structured context
# happens to hold.
_SAME_TURN_CLAUSE_SPLIT = re.compile(r"[.!?;]+|\s+(?:and|then|also|but|plus)\s+")
_SAME_TURN_TOPIC = re.compile(
    r"\b(?:what|which)\s+(?:is|are|was|were)\s+([a-z0-9][a-z0-9\s+#'’-]{0,30})$|"
    r"\b(?:who\s+(?:is|are|was|were)|like|about|tell\s+me\s+about|define|"
    r"explain|meaning\s+of)\s+([a-z0-9][a-z0-9\s+#'’-]{0,30})$",
)
_SAME_TURN_VAGUE = frozenset({
    "it", "its", "this", "that", "these", "those", "they", "them", "their",
    "him", "her", "he", "she", "one", "ones", "thing", "things", "stuff",
    "purpose", "point", "matter", "difference", "example", "examples",
    "use", "uses", "used", "using", "work", "works", "working", "time",
    "way", "ways", "part", "parts", "kind", "sort", "type", "types",
})

# Reference-only words that never count as an explicitly-named topic.
_PRONOUN_ONLY = frozenset({
    "it", "its", "this", "that", "these", "those", "they", "them", "their",
    "he", "him", "his", "she", "her", "the other one", "other one",
})

# Discourse particles that never name an entity.
_DISCOURSE_STOPWORDS = frozenset({
    "you", "me", "i", "we", "us", "your", "my", "our", "he", "she",
    "it", "there", "here", "now", "then", "this", "that", "the", "a",
    "an", "him", "her", "them", "everything", "something", "anything",
})

# Sentence-opening words that are not proper names.
_SENTENCE_STARTERS = frozenset({
    "what", "who", "when", "where", "why", "how", "the", "a", "an", "tell",
    "ask", "do", "does", "did", "can", "could", "would", "should", "may",
    "please", "and", "but", "then", "so", "is", "are", "was", "were",
    "i", "you", "we", "they", "he", "she", "it", "please", "have", "has",
    "had", "define", "explain", "describe", "open", "close", "play", "find",
    "search", "read", "show", "set", "turn", "let", "give", "whats",
})

# Words that mark a proper-name phrase as a place rather than a person.
_PLACE_PREFIX = frozenset({
    "north", "south", "east", "west", "united", "new", "san", "santa",
    "los", "las", "el", "la", "the", "st", "saint", "mount", "lake",
    "cape", "great", "port", "fort", "upper", "lower", "middle",
})
_PLACE_SUFFIX = frozenset({
    "states", "kingdom", "republic", "islands", "island", "city", "coast",
    "valley", "mountain", "mountains", "national", "park", "sea", "river",
})

# "the <role> of <Place>" — anchor place so "its capital" resolves.
_ROLE_PLACE = re.compile(r"\b(?:president|prime\s+minister|monarch|king|queen|"
                         r"capital|population|currency|government|leader|pm|"
                         r"ceo|chancellor|governor)\s+of\s+([A-Z][A-Za-z ]+)", re.I)

# Role heads that can anchor a role-ellipsis follow-up ("who is the president")
# or a demonstrative-with-head ("who are those president"). Kept as a whitelist
# so non-role predicates ("president it", "most favorable country in this war")
# never pollute entity memory (R1).
_PERSONAL_ROLE_HEADS = frozenset({
    "president", "prime", "minister", "monarch", "king", "queen", "pm",
    "ceo", "chairman", "chairwoman", "chancellor", "leader", "governor",
    "mayor", "captain", "secretary", "speaker", "ambassador", "director",
    "dictator", "tsar", "czar", "emperor", "chief", "head",
}.union({"presidents", "monarchs", "leaders", "governors", "kings", "queens"}))

# Bare role/question form: "who is the president" / "who are the presidents".
_ROLE_ELLIPSIS = re.compile(r"^who\s+(?:is|was|are|were)\s+(?:the\s+)?(.+?)\s*\??$", re.I)

# Words directly after a demonstrative that mean the demonstrative is used as
# a determiner over a content noun ("this war", "those countries") rather than
# as a standalone referent ("why did that happen"). If the following word is
# not on this list it is treated as a nominal head and the bare demonstrative
# is never blindly substituted (R2).
_DEM_HEAD_EXCLUDE = frozenset({
    "is", "are", "was", "were", "do", "does", "did", "have", "has", "had",
    "will", "would", "can", "could", "should", "shall", "may", "might",
    "be", "been", "being", "happen", "happens", "happened", "go", "goes",
    "went", "gone", "come", "came", "mean", "means", "meant", "use", "uses",
    "used", "start", "starts", "started", "stop", "stops", "stopped",
    "get", "got", "gotten", "take", "took", "taken", "look", "looks",
    "turn", "turns", "turned", "tell", "told", "show", "shows", "know",
    "knows", "knew", "work", "works", "worked", "and", "or", "so", "then",
    "but", "because", "of", "for", "to", "in", "on", "at", "with", "by",
    "from", "why", "what", "when", "where", "how", "who", "which", "not",
    "i", "you", "we", "they", "it", "he", "she",
})

_PERSON_HARVEST = re.compile(
    r"\b(?:is|was)\s+(?:the\s+)?(?:[A-Z][a-z]{1,}\s+){0,3}[A-Z][a-zA-Z.'’\[\]()-]{1,}\b",
)


@dataclass
class ReferenceResolution:
    """Outcome of deterministic reference resolution for one user turn."""
    status: str = _REF_STATUS_NOT_NEEDED
    resolved: str = ""
    clarification: str = ""
    entity: str = ""
    entity_type: str = ""
    source: str = ""
    live_followup_entity: str = ""
    candidates: list = field(default_factory=list)
    latency_ms: float = 0.0


@dataclass
class ConversationContext:
    """Structured working memory for the current conversation / active voice session.

    Ownership rules:
      - ``history`` is an N-turn rolling buffer.
      - ``current_media`` / ``previous_media`` / ``last_search`` are populated
        exclusively by tool-result evidence — never by the LLM.
      - Ephemeral fields (active_goal, pending_reference, current_plan …) are
        cleared on session expiry but media/search context is optionally
        retained so repeated sessions can pick up where a fresh one left off.
    """
    last_transcript: str = ""
    last_intent: Optional[Intent] = None
    last_response: str = ""
    pending_intent: Optional[Intent] = None
    confirmation_start_time: float = 0.0

    # Phase 6 & 22 & 23
    current_plan: Optional[ActionPlan] = None
    current_goal: Optional[GoalContext] = None
    last_search_query: str = ""
    last_search_results: list = field(default_factory=list)
    last_tool_result: dict = None

    # Voice action context (current single-turn state for follow-ups)
    last_opened_application: str = ""
    last_opened_website: str = ""
    active_media: str = ""

    # Phase 20: N-turn rolling context
    history: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Structured working memory — short-term session context
    # ------------------------------------------------------------------
    conversation_turn: int = 0
    active_app: str = ""
    active_website: str = ""

    last_action: dict = field(default_factory=dict)       # {type, query, target}
    last_search: dict = field(default_factory=dict)       # {provider, query, results}
    current_media: dict = field(default_factory=dict)     # {provider, query, title, url, video_id}
    previous_media: list = field(default_factory=list)
    pending_reference: str = ""
    active_goal: str = ""

    # Phase 1-4 additions — persistent conversation state
    active_topic: str = ""              # currently discussed topic
    entities: dict = field(default_factory=dict)  # extracted entities {name: value}
    pending_reference: str = ""         # reference being resolved (e.g. "that", "it")
    last_user_query: str = ""           # last full user query for reference

    # Conversational context — reference resolution (raw vs resolved)
    last_raw_query: str = ""            # raw user transcript for this turn
    last_resolved_query: str = ""       # query text sent to RAG/reasoner
    last_resolution_status: str = _REF_STATUS_NOT_NEEDED
    current_person: str = ""            # last speaker/person the user asked about
    current_person_gender: str = ""     # "male" | "female" | "" (from refs)
    current_place: str = ""             # last place the user asked about
    current_entity: str = ""            # last non-person entity asked about
    current_group: str = ""             # last group/organization asked about
    live_topic: str = ""                # entity focus of the last LIVE_WEB answer
    last_research: Optional[object] = None  # last ResearchResponse (Phase 1/2)
    active_entity: str = ""            # resolved clean focus entity for last turn
    active_entity_type: str = ""       # PERSON | PLACE | EVENT | ENTITY | ""
    active_question_type: str = ""     # QUESTION | FOLLOW_UP | CHAT | UNKNOWN
    recent_turns_max: int = 8           # recency window for reference candidates
    _entity_memory: list = field(default_factory=list)  # [{name,type,gender,seq}]
    _entity_seq: int = 0

    def activate_entity(self, name: str, etype: str) -> None:
        """Record the structured focus of the last resolved turn.

        ``active_entity`` holds a *clean* resolved entity/topic label (never
        a sentence fragment or accumulated query), so consumers like the
        role-ellipsis builder and the research gateway read context without
        re-parsing user wording (Phase 3 pre-requisite).
        """
        self.active_entity = (name or "").strip().lower()
        self.active_entity_type = etype or ""

    def push_turn(self):
        if self.last_transcript or self.last_intent:
            self.conversation_turn += 1
            self.history.append({
                "transcript": self.last_transcript,
                "resolved": self.last_resolved_query or self.last_transcript or "",
                "intent": self.last_intent,
                "response": self.last_response,
                "tool_result": self.last_tool_result,
                "search_query": self.last_search_query,
                "opened_application": self.last_opened_application,
                "opened_website": self.last_opened_website,
                "active_media": self.active_media,
            })
            if len(self.history) > 5:
                self.history.pop(0)

    def clear_ephemeral(self):
        """Clear ephemeral state on session expiry.

        Clears active_goal, pending_reference, current_plan, current_goal,
        pending_intent, and pending_intent.  Retains last_search / current_media
        as optionally-reusable context across sessions.
        """
        self.active_goal = ""
        self.pending_reference = ""
        self.current_plan = None
        self.current_goal = None
        self.pending_intent = None
        # Also clear persistent conversation state on new session
        self.active_topic = ""
        self.entities = {}
        # Conversational reference context is per-session too.
        self.last_raw_query = ""
        self.last_resolved_query = ""
        self.last_resolution_status = _REF_STATUS_NOT_NEEDED
        self.current_person = ""
        self.current_person_gender = ""
        self.current_place = ""
        self.current_entity = ""
        self.current_group = ""
        self.live_topic = ""
        self.last_research = None
        self.active_entity = ""
        self.active_entity_type = ""
        self.active_question_type = ""
        self._entity_memory = []
        self._entity_seq = 0

    @staticmethod
    def _extract_results(res_obj) -> list:
        if not res_obj:
            return []
        if isinstance(res_obj, dict):
            return res_obj.get("results") or []
        if hasattr(res_obj, "execution") and hasattr(res_obj.execution, "raw_tool_result"):
            raw = res_obj.execution.raw_tool_result
            if isinstance(raw, dict):
                return raw.get("results") or []
        if hasattr(res_obj, "raw_tool_result") and isinstance(res_obj.raw_tool_result, dict):
            return res_obj.raw_tool_result.get("results") or []
        return []
    # ------------------------------------------------------------------
    # Conversational follow-up machinery (Phases 2-4)
    # ------------------------------------------------------------------

    def update_topic(self, transcript: str):
        """Track the active conversational topic from *transcript*.

        Knowledge-question and topic-keyword phrasing sets ``active_topic`` and
        records grounded entity categories; explicit switch-away phrases clear
        it so the next topic wins. Deterministic, no model call.
        """
        low = transcript.lower().strip()
        if not low:
            return
        if re.search(r"\b(actually|forget|never mind|switch topic|onto something else)\b", low):
            self.active_topic = ""
            return
        topic = None
        for pat in (
            r"\b(tell|ask|explain|describe)\s+(?:me\s+)?about\s+(.+?)\??$",
            r"\bwhat\s+(?:is|are)\s+(?:the\s+)?(.+?)\??$",
            r"\b(?:backend|frontend|voice|reasoning|rag|stt|tts|architecture|deployment)\b",
        ):
            m = re.search(pat, low)
            if m:
                topic = (m.group(m.lastindex) if m.lastindex else m.group(0)).strip().rstrip("?!. ")
                break
        if topic and len(topic) > 2:
            self.active_topic = topic
            self._extract_entities_from_topic(topic)

    def _extract_entities_from_topic(self, topic: str) -> None:
        """Record entity categories grounded in *topic* (first mention wins)."""
        for key, pat in _CONV_ENTITY_PATTERNS.items():
            if re.search(pat, topic, re.I) and key not in self.entities:
                self.entities[key] = topic

    def resolve_reference(self, transcript: str) -> tuple:
        """Resolve pronouns / cross-turn references in *transcript*.

        Returns ``(resolved_text, success)``. Grounds system-subject pronouns
        ("does it use", "why did we choose") on the assistant, demonstratives
        ("that", "this", "it") on the active topic / entities, and handles
        "what about …?" / "which one?" phrasing. Deterministic.
        """
        text = transcript.strip()
        low = text.lower()
        if not text:
            return text, False

        candidates = []
        if self.active_topic:
            candidates.append(("topic", self.active_topic))
        for name, val in self.entities.items():
            candidates.append((name, str(val)))
        if not candidates:
            return text, False
        anchor = candidates[0][1]

        m = re.search(r"\bwhat about\s+(it|that|this)\b", low)
        if m:
            return f"what about {anchor}?", True

        resolved = text
        grounded = False

        # System-subject pronouns beside an implementation verb refer to the
        # assistant. do/does/did are deliberately NOT included: "what do you
        # mean" or "how do you spell X" ask about the user/topic, not Friday.
        if re.search(r"\b(it|we|you)\b", low) and re.search(
            r"\b(use|uses|used|choose|chose|chosen|pick|picked|build|built|"
            r"make|made|implement|implemented|create|created)\b",
            low,
        ):
            resolved, n = re.subn(r"\b(it|we|you)\b", _ASSISTANT_NAME, resolved, flags=re.I)
            grounded = grounded or n > 0

        # Demonstratives / leftover pronouns anchor on the active topic/entity.
        # A demonstrative directly followed by a content word ("this war",
        # "those countries") is a determiner over a noun phrase, not a bare
        # referent — substituting would splice the anchor into the sentence and
        # corrupt the query (R2). A referent that re-contains the pronoun
        # ("in this war" as the entity) is likewise never re-injected.
        for pron, ref in (("that", anchor), ("this", anchor), ("it", anchor)):
            if pron in ("this", "that") and self._dem_follows_noun(resolved.lower(), pron):
                continue
            if ref and pron in ref.lower().split():
                continue
            resolved, n = re.subn(r"\b" + re.escape(pron) + r"\b", ref, resolved, flags=re.I)
            grounded = grounded or n > 0

        if grounded:
            return resolved, True

        if re.search(r"\bwhich one\b", low) and len(candidates) == 1:
            return anchor, True

        return text, False

    _CONV_FRAGMENT = re.compile(
        r"^(?:tell\s+me\s+more|go\s+on|continue|elaborate|what\s+about|"
        r"what\s+do\s+you\s+mean|why|how|who|what|when|where|and|but|so|then|"
        r"yes|no|okay|ok|sure|hmm|huh)\b",
        re.I,
    )

    def _substantive_prior(self, history, low: str) -> str:
        """Most recent prior turn worth using as an anchor subject.

        Skips conversational fragments, reference-only turns and any turn whose
        wording is already contained in the current text, so a resolved query
        never accumulates an earlier question's words.
        """
        for turn in reversed((list(history or []))[-5:]):
            t = str((turn or {}).get("transcript", "")).strip()
            if not t or len(t.split()) < 3 or t.lower() == low:
                continue
            if self._CONV_FRAGMENT.match(t) and len(t.split()) <= 5:
                continue
            if t.lower() in low:
                continue
            return t
        return ""

    def _role_ellipsis_query(self, text: str) -> str:
        """Build a clean role-of-anchor question for bare role phrasing.

        "who is the president" after a turn about a country becomes
        "who is the president of russia" — grounded on the structured lexical
        anchor, never a concatenation of the previous query (R2). Returns ""
        when the phrasing is not a bare personal-role question, or when no
        anchor is available.
        """
        m_role = _ROLE_ELLIPSIS.match((text or "").lower().strip())
        if not m_role:
            return ""
        role = m_role.group(1).strip()
        role = re.sub(r"^(?:our|their|my|his|her|a|an)\s+", "", role).strip()
        role_tokens = [t for t in role.split() if t]
        if not role_tokens or " of " in role:
            return ""
        # Every token must itself be a role word: "the president" is elliptical,
        # "the king charles iii" is a resolved, complete query.
        for token in role_tokens:
            head = token[:-1] if token.endswith("s") else token
            if head not in _PERSONAL_ROLE_HEADS:
                return ""
        anchor = self._lexical_anchor()
        if not anchor:
            return ""
        head = "presidents" if role_tokens[-1].endswith("s") else role
        verb = "are" if head.endswith("s") else "is"
        return f"who {verb} the {head} of {anchor}"

    def rewrite_followup(self, transcript: str, history=None) -> str:
        """Rewrite a short conversational follow-up into a standalone query.

        Rewrites genuine follow-ups (pronoun-bearing, or short question-led
        phrasing when we have prior conversational grounding) into standalone,
        retrieval-friendly queries. Plain first-turn questions pass through
        unchanged. Deterministic, no model call.
        """
        text = transcript.strip()
        low = text.lower()
        if not text:
            return text

        # "what do you mean / by X?" is a clarification request, not a question
        # about the assistant. Rewrite it into a grounded "what is X?" so it
        # never becomes "what do friday mean" (P6). Runs before the pronoun/
        # history guard because it is a self-contained rewrite.
        m_mean = re.match(
            r"^what\s+do(?:es)?\s+(?:you|we|it|they)\s+mean(?:\s+by\s+(.+?))?\??$",
            low,
        )
        if m_mean:
            subject = (m_mean.group(1) or "").strip()
            if not subject:
                subject = self.active_topic or ""
            if not subject:
                for turn in reversed((list(history or []))[-5:]):
                    t = str((turn or {}).get("transcript", "")).strip()
                    if t and len(t.split()) >= 2:
                        subject = t
                        break
            if subject:
                # Strip any "what is / what are" scaffold before re-asking.
                subject = re.sub(
                    r"^(?:what\s+(?:is|are)\s+(?:the\s+)?|what\s+is\s+)",
                    "", subject, flags=re.I,
                ).strip().rstrip("?!")
                if subject:
                    return f"what is {subject}?"
            return text

        # A bare role question ("who is the president") is elliptical, not a
        # complete query. Ground it on the structured anchor when one exists,
        # otherwise pass it through untouched — the history-append path below
        # would splice the previous turn's wording onto it (query accumulation,
        # R2).
        if _ROLE_ELLIPSIS.match(low):
            return self._role_ellipsis_query(text) or text

        is_short = bool(_CONV_FOLLOWUP_START.match(low)) and len(text.split()) <= 8
        has_pronoun = bool(_CONV_PRONOUN_RE.search(text))
        # "this war" / "that country" uses the demonstrative as a determiner,
        # not as a bare referent — count it only as a pronoun when it stands
        # in object position ("why did that happen").
        for dem in ("this", "that"):
            if has_pronoun and self._dem_follows_noun(low, dem):
                has_pronoun = False
        has_history = any(
            str((turn or {}).get("transcript", "")).strip()
            for turn in (list(history or [])[-5:])
        )
        if not (has_pronoun or (is_short and has_history)):
            return text

        resolved_text, grounded = self.resolve_reference(text)
        if grounded:
            return resolved_text

        # A follow-up that already carries its own subject is a complete query:
        # leave it alone. Only minimal phrasings (or bare connectors) qualify
        # for the topic anaphora extension used below.
        words = text.split()
        is_connector = bool(re.match(r"^(and|but|so|then)\b", low))
        if not (has_pronoun or len(words) <= 4 or is_connector):
            return text

        # No grounded pronoun: recover the most recent substantive prior query.
        # A conversational fragment ("tell me more about him", "and then?") is
        # never an anchor — appending it would splice the previous turn's
        # wording into the new query (query accumulation, R1/R2).
        prior = self._substantive_prior(history, low)
        if not prior:
            return text

        anchor = self.active_topic or ""
        if not anchor:
            for name in ("voice", "reasoning", "backend", "stt", "tts", "api"):
                if name in self.entities:
                    anchor = self.entities[name]
                    break
        if not anchor:
            anchor = prior

        if re.match(r"^why\b", low):
            return f"why did friday use {anchor}?"
        if re.match(r"^how\b", low):
            return f"how does {anchor} work?"
        if re.match(r"^which\b", low):
            return f"which one is {anchor}?"
        # Bare continuation connectors ("and after?", "so then?") anchor straight
        # on the recovered prior turn — the richest retrievable subject we have.
        # The anchor is only appended when it is not already part of the text,
        # so re-asking an anchored topic never yields "what is rather (rather)".
        anchor_low = anchor.lower()
        if is_connector and anchor_low not in low:
            return f"{text} ({prior})"
        if anchor_low not in low:
            return f"{text} ({anchor})"
        return text

    # ------------------------------------------------------------------
    # Conversational reference resolution (person / group / entity / place)
    # ------------------------------------------------------------------

    def observe_turn(self, transcript: str) -> None:
        """Record typed entities mentioned in a *raw* user turn.

        Extracts people (who-questions, "tell me about X and Y"), roles,
        places (role-of-place) and events, then pushes them into the bounded
        recency-aware entity memory. Runs before resolution so a follow-up
        turn can anchor on entities its own predecessor introduced.
        """
        if not transcript or not transcript.strip():
            return
        low = transcript.lower().strip().rstrip("?.! ")
        pushed = []

        m_about = re.search(
            r"\b(?:tell\s+me\s+about|ask\s+about|about)\s+(.+?)(?:\?|$)",
            low, re.I,
        )
        if m_about:
            chunk = m_about.group(1).strip()
            chunk = re.sub(r"^(?:the|this|that)\s+", "", chunk).strip()
            if chunk.lower() in _PRONOUN_ONLY or chunk.lower() in _DISCOURSE_STOPWORDS:
                chunk = ""
            # A chunk that itself opens with a question/verb word is a sentence
            # fragment ("about what happened recently", "about who is winning"),
            # not a topic name — never store it as an entity (R1).
            if chunk and re.match(
                r"^(?:who|what|when|where|why|how|which|is|are|was|were|"
                r"do|does|did)\b", chunk, re.I,
            ):
                chunk = ""
            if chunk and re.search(r"\b(?:war|conflict|crisis|election|revolt|battle|match|final)\b", chunk):
                pushed.append(("event", chunk, ""))
            elif re.search(r"\b(and|,| & | or )\b", chunk) and not re.search(
                r"\b(war|conflict|crisis)\b", chunk,
            ):
                parts = [p.strip().rstrip(",") for p in re.split(r"\s+and\s+|,|&|\s+or\s+", chunk)]
                parts = [p for p in parts if p and len(p) > 1]
                if len(parts) > 1:
                    for p in parts:
                        pushed.append(("person", p, ""))
                else:
                    pushed.append(("entity", parts[0], ""))
            elif re.match(r"^[A-Za-z]", chunk) and not re.match(r"^[a-z]", chunk[0]):
                pushed.append(("person", chunk, ""))
            else:
                pushed.append(("entity", chunk, ""))

        m_role = re.search(
            r"\bwho\s+(?:is|was|are|were)\s+(?:the\s+)?(.*?)(?:\?|\s*$)",
            low,
        )
        if m_role and m_role.group(1):
            subject = m_role.group(1).strip().rstrip("?. ")
            if subject and len(subject) > 2:
                role = self._role_subject(subject)
                if role is not None:
                    if not role.startswith("the "):
                        role = "the " + role
                    pushed.append(("person_role", role, ""))

        m_place = _ROLE_PLACE.search(low)
        if m_place:
            place = m_place.group(1).strip().rstrip("?. ")
            if re.match(r"^[A-Z]", place):
                pushed.append(("place", place, ""))
            elif len(place) > 2:
                pushed.append(("place", place, ""))

        m_ev = re.search(
            r"\b((?:[A-Z][A-Za-z0-9'’&-]*)(?:\s+(?:[A-Z][A-Za-z0-9'’&-]*|of|the|and))*)\s+"
            r"(war|conflict|crisis|election|revolt|battle|match|final)\b",
            transcript,
        )
        if m_ev:
            evname = (m_ev.group(1) + " " + m_ev.group(2)).strip()
            evname = re.sub(r"^(?:the|a|an)\s+", "", evname, flags=re.I).strip()
            first = re.split(r"[\s-]+", evname.lower())[0]
            if first not in _DISCOURSE_STOPWORDS and first not in _SENTENCE_STARTERS:
                pushed.append(("event", evname, ""))

        # Proper-name mentions in the *raw* (case-preserved) transcript:
        # "Elon Musk", "Tesla", "King Charles III".
        for np in re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*(?:\s+[IVX]+)?\b", transcript):
            words = np.split()
            if words[0].lower() in _SENTENCE_STARTERS:
                continue
            name = " ".join(words).lower()
            if name in _DISCOURSE_STOPWORDS or name in _PRONOUN_ONLY:
                continue
            already = any(name == (e["name"] if isinstance(e, dict) else str(e[1]).lower())
                          for e in pushed + self._entity_memory)
            if already:
                continue
            # A capitalized fragment already covered by an event phrase
            # ("Russia Ukraine" inside "Russia Ukraine war") is part of that
            # event, not a person — never demote it to PERSON.
            if any(p[0] == "event" and name in p[1].lower() for p in pushed):
                continue
            if len(words) >= 2:
                if (words[0].lower() in _PLACE_PREFIX
                        or words[-1].lower() in _PLACE_SUFFIX):
                    pushed.append(("place", name, ""))
                else:
                    pushed.append(("person", name, ""))
            elif len(words[0]) >= 3:
                pushed.append(("entity", name, ""))

        for etype, name, gender in pushed:
            if name and re.search(r"[A-Za-z]", name):
                self.push_entity(name, {"person": "PERSON", "person_role": "PERSON_ROLE",
                                        "place": "PLACE", "event": "EVENT",
                                        "entity": "ENTITY"}.get(etype, etype), gender)

    def _role_subject(self, subject: str) -> Optional[str]:
        """Return a clean role phrase from a who-question subject, else None.

        Accepts "the president", "president of Britain", "current president of
        russia" but REJECTS pronoun / nondescript fragments ("it", "president
        it", "most favorable country in this war", "those president") that are
        not a genuine role head, so garbage never pollutes entity memory (R1).
        """
        low = subject.lower().strip("?!. ")
        if len(low) < 2:
            return None
        if low in _PRONOUN_ONLY or low in _DISCOURSE_STOPWORDS:
            return None
        low = re.sub(r"^the\s+", "", low).strip()
        if not low:
            return None
        if re.match(r"^(this|that|these|those)\b", low):
            return None
        role, sep, place = low.partition(" of ")
        role = role.strip()
        place = place.strip()
        role_head = any(t in _PERSONAL_ROLE_HEADS for t in role.split()[:2])
        if place:
            place = re.sub(r"^(?:the|a|an)\s+", "", place, flags=re.I).strip()
            if not place:
                return None
            if place in _PRONOUN_ONLY or place in _DISCOURSE_STOPWORDS:
                return None
            if re.search(r"\b(these|those|that|this|it|them|they|were|are|did|does)\b", place):
                return None
            if len(place.split()) > 4:
                return None
            if not role_head:
                return None
            return f"{role} of {place}"
        toks = low.split()
        if not role_head or len(toks) > 3:
            return None
        if toks[-1] in _PRONOUN_ONLY or toks[-1] in _DISCOURSE_STOPWORDS:
            return None
        return low

    def push_entity(self, name: str, etype: str, gender: str = "") -> str:
        """Push a typed entity into the bounded recency memory (recency bump)."""
        name = re.sub(r"\s+", " ", name).strip().lower().rstrip("?. ")
        if not name or len(name) < 2 or not re.search(r"[a-z]", name):
            return ""
        old = next((e for e in self._entity_memory if e["name"] == name), None)
        self._entity_memory = [
            e for e in self._entity_memory if e["name"] != name
        ]
        self._entity_seq += 1
        gender = gender or ((old or {}).get("gender", "") if old else "")
        self._entity_memory.append({
            "name": name, "type": etype, "gender": gender, "seq": self._entity_seq,
        })
        if len(self._entity_memory) > self.recent_turns_max:
            self._entity_memory = self._entity_memory[-self.recent_turns_max:]
        if etype in ("PLACE",):
            self.current_place = name
        elif etype in ("GROUP",):
            self.current_group = name
        elif etype in ("PERSON", "PERSON_ROLE"):
            self.current_person = name
            if gender and gender in ("male", "female"):
                self.current_person_gender = gender
        elif etype in ("EVENT", "ENTITY", "ORGANIZATION"):
            self.current_entity = name
        return name

    def _candidates(self, token: str) -> list:
        """Compatible, recency-ordered candidate entities for *token*."""
        low = token.lower()
        mem = list(self._entity_memory)
        if low in ("he", "him", "his"):
            males = [e for e in mem if e["type"] in ("PERSON", "PERSON_ROLE") and e["gender"] == "male"]
            if males:
                return males
            return [e for e in mem if e["type"] in ("PERSON", "PERSON_ROLE") and e["gender"] in ("", "unknown")]
        if low in ("she", "her"):
            females = [e for e in mem if e["type"] in ("PERSON", "PERSON_ROLE") and e["gender"] == "female"]
            if females:
                return females
            return [e for e in mem if e["type"] in ("PERSON", "PERSON_ROLE") and e["gender"] in ("", "unknown")]
        if low in ("they", "them", "their"):
            groups = [e for e in mem if e["type"] in ("GROUP", "ORGANIZATION")]
            if groups:
                return groups
            return [e for e in mem if e["type"] in ("ENTITY", "EVENT", "PLACE")]
        if low in ("it", "its"):
            nonperson = [e for e in mem if e["type"] not in ("PERSON", "PERSON_ROLE")]
            if nonperson:
                return nonperson
            return [e for e in mem if e["type"] in ("PERSON", "PERSON_ROLE")]
        if low in ("here", "there"):
            return [e for e in mem if e["type"] == "PLACE"]
        if low in ("other", "the other one"):
            return list(mem)
        return list(mem)

    def _apply_ref(self, text: str, token: str, entity: str) -> str:
        entity = re.sub(r"\s+", " ", entity).strip().lower()
        if not entity:
            return text
        # Never re-inject a referent that literally contains the pronoun being
        # swapped — that would breed "in most favorable country in most
        # favorable country in this war" (recursive self-substitution, R2).
        if token.lower() in entity.split():
            return text
        if token.lower() in ("his", "her", "its", "their"):
            repl = entity + "'s"
        else:
            repl = entity
        return re.sub(r"\b" + re.escape(token) + r"\b", repl, text, flags=re.I)

    def _dem_follows_noun(self, low: str, token: str) -> bool:
        """True when a bare demonstrative is followed by a content word.

        "this war" / "those countries" use the demonstrative as a determiner
        over a noun phrase (no bare referent); "why did that happen" keeps it
        as a standalone object. The following word is a head when it is not on
        the auxiliary / verb / connective exclusion set.
        """
        m = re.search(r"\b" + re.escape(token) + r"\s+([a-z]{2,})\b", low)
        if not m:
            return False
        return m.group(1).lower() not in _DEM_HEAD_EXCLUDE

    def _lexical_anchor(self) -> str:
        """Most recent place/event/entity name usable as a role-ellipsis anchor."""
        for e in reversed(self._entity_memory):
            if e["type"] in ("PLACE", "EVENT", "ENTITY", "GROUP", "ORGANIZATION"):
                return e["name"]
        return ""

    def _anchor_type(self, anchor: str) -> str:
        """Entity type backing a lexical anchor name ("" when not in memory)."""
        for e in reversed(self._entity_memory):
            if e["name"] == anchor:
                return e["type"]
        return ""

    @staticmethod
    def _dedup_resolved(text: str) -> str:
        """Collapse adjacent duplicate words left behind by substitution."""
        prev = None
        out = []
        for w in (text or "").split():
            if w.lower() == prev:
                continue
            out.append(w)
            prev = w.lower()
        return " ".join(out)

    def _harvest_person(self, response: str) -> str:
        """Extract a properly-cased person name mentioned as a role holder."""
        if not response:
            return ""
        m = _PERSON_HARVEST.search(response)
        if m:
            name = m.group(0).strip()
            name = re.sub(r"^(?:is|was)(?:st|n't)?\s+", "", name, flags=re.I).strip()
            if name and re.match(r"^[A-Z]", name) and " " in name:
                return name
        m2 = re.search(
            r"([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]*)*(?:\s+[IVX]+)?)\s+"
            r"(?:is|was)\s+(?:the\s+)?(?:president|prime\s+minister|monarch|king|queen|"
            r"ceo|chancellor|leader|pm|governor)\b",
            response,
        )
        if m2 and not re.match(r"^\w+\s+(?:is|are|was)", m2.group(1)):
            return m2.group(1)
        return m2.group(1) if m2 else ""

    def _infer_gender(self, query: str, response: str) -> str:
        q = query.lower()
        if _FEMALE_PRONOUNS.search(q) or re.search(r"\bshe\s+(?:is|was)|^her\b", q):
            return "female"
        if _MALE_PRONOUNS.search(q) or re.search(r"\bhe\s+(?:is|was)\b", q):
            return "male"
        if re.search(r"\bshe\s+(?:is|was)\b", (response or "").lower()):
            return "female"
        if re.search(r"\bhe\s+(?:is|was)\b", (response or "").lower()):
            return "male"
        return ""

    def resolve_conversation_reference(self, transcript: str, history=None) -> ReferenceResolution:
        """Resolve conversational references (pronouns / ellipsis) deterministically.

        Returns a :class:`ReferenceResolution`. Only reference-bearing or
        elliptical phrasings are rewritten; when no compatible antecedent
        exists the turn is left untouched (``not_needed``) rather than
        guessed at, and explicitly-named follow-up topics pass through as
        complete queries.
        """
        t0 = time.monotonic()
        raw = transcript or ""
        low = (raw.lower().strip()).rstrip("?!. ")
        if not low:
            return ReferenceResolution(status=_REF_STATUS_NOT_NEEDED, resolved=raw, latency_ms=0.0)

        wa = _WHAT_ABOUT.search(low)
        tell = _TELL_MORE.match(low) if not wa else None
        whyf = _WHY_FOLLOWUP.match(low) if (not wa and not tell) else None

        has_male = bool(_MALE_PRONOUNS.search(low))
        has_female = bool(_FEMALE_PRONOUNS.search(low))
        has_group = bool(_GROUP_PRONOUNS.search(low))
        has_entity_pron = bool(_ENTITY_PRONOUNS.search(low))
        has_dem = bool(_DEMONSTRATIVES.search(low))
        has_place = bool(_PLACE_DEICTICS.search(low))

        # Role ellipsis: "who is the president" / "who are the presidents"
        # after a prior turn about a country/event becomes a clean role-of
        # question grounded on the structured lexical anchor — never a string
        # concatenation of the previous query (R2, Phase 3 pre-requisite).
        # Checked BEFORE the not-a-reference early return because a bare role
        # question carries no pronoun of its own.
        if not (wa or tell or whyf or has_male or has_female or has_group
                or has_entity_pron or has_dem or has_place):
            role_query = self._role_ellipsis_query(low)
            if role_query:
                anchor = role_query.rsplit(" of ", 1)[-1]
                return ReferenceResolution(
                    status=_REF_STATUS_RESOLVED, resolved=role_query,
                    entity=anchor, entity_type=self._anchor_type(anchor),
                    source="role-ellipsis",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

        if not (has_male or has_female or has_group or has_entity_pron or has_dem or
                has_place or wa or tell or whyf):
            return ReferenceResolution(
                status=_REF_STATUS_NOT_NEEDED, resolved=raw,
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        mode = "pronoun"
        obj = ""
        ellipsis_kind = ""
        if wa:
            mode = "what-about"
            obj = re.sub(r"\b(do\s+you\s+(?:know|think)\s+|is\s+there)\b", "",
                         wa.group(1)).strip().lower()
            obj = re.sub(r"^(?:about|with|for|on)\s+", "", obj).strip()
            if obj and obj not in _PRONOUN_ONLY:
                return ReferenceResolution(
                    status=_REF_STATUS_NOT_NEEDED, resolved=raw,
                    entity=obj, entity_type="QUERY",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
        elif tell:
            mode = "ellipsis"
            ellipsis_kind = "tell"
            obj = re.sub(r"^(?:about|more\s+about)\s+", "",
                         (tell.group(1) or "").strip().lower()).strip()
            if obj and obj not in _PRONOUN_ONLY:
                return ReferenceResolution(
                    status=_REF_STATUS_NOT_NEEDED, resolved=raw,
                    entity=obj, entity_type="QUERY",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
        elif whyf:
            mode = "ellipsis"
            ellipsis_kind = "why"

        ref_token = self._ref_token(low, obj)
        candidates = self._candidates(ref_token if mode != "what-about" else obj)
        candidates = [c for c in candidates
                      if c["seq"] >= self._entity_seq - self.recent_turns_max]

        # Same-turn repeated topic wins over older structured context: a phrase
        # named twice inside this utterance is the closest antecedent there is
        # (section 17). Restricted to non-gendered, non-group references so the
        # person/group ambiguity rules keep priority.
        if mode == "pronoun" and ref_token in ("it", "this", "there"):
            same_turn = self._same_turn_anchor(low)
            if same_turn:
                resolved = raw
                for t in self._tokens_for(low):
                    if t in ("this", "that", "these", "those") and self._dem_follows_noun(
                            resolved.lower(), t,
                    ):
                        continue
                    resolved = self._apply_ref(resolved, t, same_turn)
                resolved = self._dedup_resolved(resolved)
                if resolved != raw:
                    return ReferenceResolution(
                        status=_REF_STATUS_RESOLVED, resolved=resolved,
                        entity=same_turn, entity_type="TOPIC",
                        source="same-turn-anchor",
                        latency_ms=(time.monotonic() - t0) * 1000,
                    )

        if not candidates:
            if ref_token in ("he", "him", "his", "she", "her"):
                return ReferenceResolution(
                    status=_REF_STATUS_UNRESOLVED, resolved=raw,
                    clarification="Who are you referring to?",
                    entity_type="PERSON", source=ref_token,
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            if ref_token in ("they", "them", "their"):
                return ReferenceResolution(
                    status=_REF_STATUS_UNRESOLVED, resolved=raw,
                    clarification="Which group are you referring to?",
                    entity_type="GROUP", source=ref_token,
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            return ReferenceResolution(
                status=_REF_STATUS_NOT_NEEDED, resolved=raw,
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        # Demonstrative-with-head-noun: "these/those <role noun>" resolves to a
        # clean plural role-of question ("who are those presidents" -> "who are
        # the presidents of {anchor}") using the structured anchor instead of
        # splicing the anchor into the raw sentence (R2).
        if has_dem:
            m_demrole = re.search(
                r"\b(?:these|those)\s+([a-z]{2,})\b", low,
            )
            if m_demrole:
                head = m_demrole.group(1)
                anchor = self._lexical_anchor()
                if anchor and head in _PERSONAL_ROLE_HEADS:
                    plural = "presidents" if head.endswith("s") else "president"
                    verb = "are" if plural == "presidents" else "is"
                    resolved = f"who {verb} the {plural} of {anchor}"
                    return ReferenceResolution(
                        status=_REF_STATUS_RESOLVED, resolved=resolved,
                        entity=anchor, entity_type=self._anchor_type(anchor),
                        source="demonstrative",
                        latency_ms=(time.monotonic() - t0) * 1000,
                    )
                if anchor and re.search(r"\b(countries|leaders|presidents)\b", head):
                    resolved = f"who are the presidents of {anchor}"
                    return ReferenceResolution(
                        status=_REF_STATUS_RESOLVED, resolved=resolved,
                        entity=anchor, entity_type=self._anchor_type(anchor),
                        source="demonstrative",
                        latency_ms=(time.monotonic() - t0) * 1000,
                    )

        best = self._best_first(candidates)
        tied = self._tier_size(best)
        if (mode in ("pronoun", "what-about")
                and ref_token in ("he", "him", "his", "she", "her", "they", "them", "their")
                and len(best) > 1 and tied > 1):
            order = sorted(best, key=lambda c: c["seq"])
            names = " or ".join(" ".join(c["name"].title().split()) for c in order[:2])
            return ReferenceResolution(
                status=_REF_STATUS_AMBIGUOUS, resolved=raw,
                clarification=f"Did you mean {names}?",
                entity=best[0]["name"], entity_type=best[0]["type"],
                candidates=[c["name"] for c in order], source=ref_token,
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        chosen = best[0]
        entity = chosen["name"]

        if mode == "ellipsis":
            if ellipsis_kind == "tell":
                return ReferenceResolution(
                    status=_REF_STATUS_RESOLVED,
                    resolved=f"tell me more about {entity}",
                    entity=entity, entity_type=chosen["type"], source="ellipsis",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            if re.search(r"\b(this|that)\b", low):
                resolved = raw
                for t in ("this", "that"):
                    if self._dem_follows_noun(low, t):
                        continue
                    resolved = self._apply_ref(resolved, t, entity)
                resolved = self._dedup_resolved(resolved)
                return ReferenceResolution(
                    status=_REF_STATUS_RESOLVED, resolved=resolved,
                    entity=entity, entity_type=chosen["type"], source="ellipsis",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            if low.startswith("why") and chosen["type"] == "EVENT":
                resolved = f"why did the {entity} happen?"
            elif low.startswith("why"):
                resolved = f"why is {entity}?"
            else:
                resolved = f"{low} ({entity})"
            return ReferenceResolution(
                status=_REF_STATUS_RESOLVED, resolved=resolved,
                entity=entity, entity_type=chosen["type"], source="ellipsis",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        if mode == "what-about":
            if obj in ("the other one", "other one"):
                others = [c for c in best if c["name"] != entity]
                if len(others) == 1:
                    return ReferenceResolution(
                        status=_REF_STATUS_RESOLVED,
                        resolved=f"what about {others[0]['name']}",
                        entity=others[0]["name"], entity_type=others[0]["type"],
                        source="what-about", latency_ms=(time.monotonic() - t0) * 1000,
                    )
                if len(others) > 1:
                    names = ", ".join(" ".join(c["name"].title().split()) for c in others[:2])
                    return ReferenceResolution(
                        status=_REF_STATUS_AMBIGUOUS, resolved=raw,
                        clarification=f"Did you mean {names}?",
                        source="what-about", latency_ms=(time.monotonic() - t0) * 1000,
                    )
            return ReferenceResolution(
                status=_REF_STATUS_RESOLVED, resolved=f"what about {entity}",
                entity=entity, entity_type=chosen["type"], source="what-about",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        resolved = raw
        for t in self._tokens_for(low):
            if t in ("this", "that", "these", "those") and self._dem_follows_noun(resolved.lower(), t):
                continue
            resolved = self._apply_ref(resolved, t, entity)
        resolved = self._dedup_resolved(resolved)
        if resolved == raw:
            return ReferenceResolution(
                status=_REF_STATUS_NOT_NEEDED, resolved=raw,
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        return ReferenceResolution(
            status=_REF_STATUS_RESOLVED, resolved=resolved,
            entity=entity, entity_type=chosen["type"], source=self._ref_source(low),
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    def _same_turn_anchor(self, low: str) -> str:
        """Topic named more than once inside a single utterance.

        Returns "" unless the *same* non-vague noun phrase is introduced at
        least twice by naming clauses in this one turn ("what is node man" +
        "like node man"). That repetition is a much stronger, turn-local
        antecedent than anything held in structured context, and it is what
        "can you tell me about it? ... like node man. what is node man?
        what's the purpose of using it?" refers to (section 17 regression).
        """
        counts: dict = {}
        order: list = []
        for clause in _SAME_TURN_CLAUSE_SPLIT.split(low or ""):
            clause = (clause or "").strip()
            if not clause:
                continue
            match = _SAME_TURN_TOPIC.search(clause)
            if not match:
                continue
            phrase = re.sub(r"[\s]+", " ", (match.group(1) or match.group(2) or "")).strip()
            phrase = re.sub(r"^(?:the|a|an|his|her|its|their)\s+", "", phrase).strip()
            if not phrase or len(phrase.split()) > 4:
                continue
            if phrase in _SAME_TURN_VAGUE or _PRONOUN_ONLY.intersection(phrase.split()):
                continue
            if not [t for t in phrase.split() if t not in _DISCOURSE_STOPWORDS]:
                continue
            if phrase in counts:
                counts[phrase] += 1
            else:
                counts[phrase] = 1
                order.append(phrase)
        for phrase in order:
            if counts[phrase] >= 2:
                return phrase
        return ""

    def _ref_token(self, low: str, obj: str) -> str:
        """Classify the strongest reference token present in the turn."""
        token = (obj or "").strip().lower()
        if token in ("he", "him", "his"):
            return "he"
        if token in ("she", "her"):
            return "she"
        if token in ("they", "them", "their"):
            return "they"
        if token in ("it", "its"):
            return "it"
        if token in ("this", "that"):
            return "this"
        if token in ("the other one", "other one"):
            return "other"
        if _MALE_PRONOUNS.search(low):
            return "he"
        if _FEMALE_PRONOUNS.search(low):
            return "she"
        if _GROUP_PRONOUNS.search(low):
            return "they"
        if _ENTITY_PRONOUNS.search(low):
            return "it"
        if _DEMONSTRATIVES.search(low):
            return "this"
        if _PLACE_DEICTICS.search(low):
            return "there"
        if token:
            return "other"
        return "this"

    def _tier_size(self, best: list) -> int:
        """Tied candidates at the strongest compatibility tier."""
        if not best:
            return 0
        top = best[0]
        if top.get("gender") in ("male", "female"):
            return len([c for c in best if c.get("gender") == top["gender"]])
        return len([c for c in best if c["type"] == top["type"]])

    def _best_first(self, candidates: list) -> list:
        """Rank candidates: gendered > unknown, named > role/group > event/
        place > entity, most-recent first."""
        def rank(c):
            gender_rank = 0 if c.get("gender") in ("male", "female") else 1
            if c["type"] == "PERSON":
                type_rank = 0
            elif c["type"] in ("PERSON_ROLE",):
                type_rank = 1
            elif c["type"] in ("GROUP", "ORGANIZATION"):
                type_rank = 2
            elif c["type"] == "EVENT":
                type_rank = 3
            elif c["type"] == "PLACE":
                type_rank = 4
            else:
                type_rank = 5
            return (gender_rank, type_rank, -c["seq"])
        return sorted(candidates, key=rank)

    def _tokens_for(self, low: str) -> list:
        tokens = []
        for pat, toks in (
            (_MALE_PRONOUNS, ("he", "him", "his")),
            (_FEMALE_PRONOUNS, ("she", "her")),
            (_GROUP_PRONOUNS, ("they", "them", "their")),
            (_ENTITY_PRONOUNS, ("it", "its")),
            (_DEMONSTRATIVES, ("this", "that", "these", "those")),
            (_PLACE_DEICTICS, ("here", "there")),
        ):
            if pat.search(low):
                tokens.extend(toks)
        return tokens

    def _ref_source(self, low: str) -> str:
        if _MALE_PRONOUNS.search(low):
            return "he"
        if _FEMALE_PRONOUNS.search(low):
            return "she"
        if _GROUP_PRONOUNS.search(low):
            return "they"
        if _ENTITY_PRONOUNS.search(low):
            return "it"
        if _DEMONSTRATIVES.search(low):
            return "this"
        if _PLACE_DEICTICS.search(low):
            return "there"
        return "other"

    def finalize_turn(self) -> None:
        """Update reference context AFTER the assistant's answer is known.

        Harvests a properly-cased person name from role-holder answers so a
        later pronoun ("who is he") resolves to the *named* person rather than
        the bare role. Runs before ``push_turn``.
        """
        query = self.last_resolved_query or self.last_raw_query or ""
        response = self.last_response or ""
        if not query or not response:
            return
        whoish = _WHO_QUESTION.search(query) or _WHO_QUESTION.search(self.last_raw_query or "")
        named = _WHO_QUESTION.search(self.last_raw_query or "")
        if whoish or named:
            person = self._harvest_person(response)
            if person:
                self.push_entity(person, "PERSON", self._infer_gender(query, response))


def _extract_results(res_obj) -> list:
    """Extract the results list from a tool result (dict or wrapped)."""
    if not res_obj:
        return []
    if isinstance(res_obj, dict):
        return res_obj.get("results") or []
    if hasattr(res_obj, "execution") and hasattr(res_obj.execution, "raw_tool_result"):
        raw = res_obj.execution.raw_tool_result
        if isinstance(raw, dict):
            return raw.get("results") or []
    if hasattr(res_obj, "raw_tool_result") and isinstance(res_obj.raw_tool_result, dict):
        return res_obj.raw_tool_result.get("results") or []
    return []


class ConversationManager:
    """
    Manages state transitions, context, system intents, confirmation, and tool execution.
    """

    def __init__(
        self,
        dry_run: bool = True,
        allow_real_execution: bool = False,
        reasoner: Optional[Reasoner] = None,
        permissions: Optional[dict] = None,
        conversation_timeout_seconds: int = 300,
        rag_service=None,
        research_agent=None,
        research_enabled: Optional[bool] = None,
        natural_conversation_enabled: Optional[bool] = None,
        natural_conversation_router=None,
    ):
        self.state_machine = StateMachine(ConversationState.IDLE)
        self.context = ConversationContext()
        self.session = ConversationSession(timeout_seconds=conversation_timeout_seconds)
        self.dry_run = dry_run
        self.allow_real_execution = allow_real_execution
        self.reasoner = reasoner or OllamaReasoner()
        # None means "use registry defaults" (all enabled) — backward compatible
        self.permissions = permissions
        self.rag_service = rag_service
        self._reasoner_rag_support: Optional[bool] = None
        self.research_agent = research_agent
        if research_enabled is None:
            research_enabled = bool(getattr(research_agent, "enabled", False))
        self.research_enabled = bool(research_enabled)
        # Natural Conversation Layer: deterministic local answers for pure
        # chatter. Enabled by default; ``None`` means "on" unless the injected
        # router says otherwise.
        self.natural_conversation_router = (
            natural_conversation_router
            if natural_conversation_router is not None
            else NaturalConversationRouter()
        )
        if natural_conversation_enabled is None:
            natural_conversation_enabled = bool(
                getattr(self.natural_conversation_router, "enabled", True)
            )
        self.natural_conversation_enabled = bool(natural_conversation_enabled)

    # ------------------------------------------------------------------
    # Active-session helpers
    # ------------------------------------------------------------------

    def _check_session_expiry(self):
        """End the active session + clear ephemeral context after user inactivity."""
        if self.session.is_expired():
            logger.info("[SESSION] Session timeout reached")
            self.session.end()
            self.context.clear_ephemeral()
            logger.info("[SESSION] Returning to wake-word mode")

    def _end_session_soft(self) -> str:
        """Explicit session end (go to sleep / stop listening) — stays running."""
        self.session.end()
        self.context.clear_ephemeral()
        logger.info("[SESSION] Explicit session end; returning to wake-word mode")
        return "Going to sleep. Say 'Hey Friday' to wake me up."

    @property
    def state(self) -> ConversationState:
        if self.state_machine.current_state == ConversationState.WAITING_FOR_CONFIRMATION:
            if self.context.confirmation_start_time > 0 and (time.time() - self.context.confirmation_start_time > 30.0):
                logger.info("Confirmation timeout expired. Auto-reverting state to LISTENING.")
                self.context.pending_intent = None
                if self.context.current_plan:
                    self.context.current_plan.state = PlanState.CANCELLED
                    self.context.current_plan = None
                self.state_machine.transition_to(ConversationState.LISTENING)
        return self.state_machine.current_state

    def start_session(self):
        """Transition from IDLE or STOPPING to LISTENING."""
        if self.state == ConversationState.STOPPING:
            self.state_machine.transition_to(ConversationState.IDLE)
        if self.state == ConversationState.IDLE:
            self.state_machine.transition_to(ConversationState.LISTENING)

    def stop_session(self):
        """Transition to STOPPING then IDLE and reset ephemeral session context."""
        self.context = ConversationContext()
        self.state_machine.transition_to(ConversationState.STOPPING)
        self.state_machine.transition_to(ConversationState.IDLE)

    def _get_short_term_context(self) -> ShortTermContext:
        action = self.context.last_intent.action if self.context.last_intent else None
        target = self.context.last_intent.target if self.context.last_intent else ""
        search_results = getattr(self.context, "last_search_results", None) or _extract_results(self.context.last_tool_result)

        tool_res_dict = self.context.last_tool_result if isinstance(self.context.last_tool_result, dict) else (
            self.context.last_tool_result.execution.raw_tool_result if hasattr(self.context.last_tool_result, "execution") else None
        )

        goal_entities = dict(self.context.current_goal.entities) if self.context.current_goal else {}
        if self.context.last_search_results == [] and self.context.last_tool_result is None:
            goal_entities.pop("search_results", None)

        return ShortTermContext(
            last_search_query=self.context.last_search_query,
            last_search_results=search_results,
            last_tool_result=tool_res_dict,
            last_action=action,
            last_target=target,
            last_transcript=self.context.last_transcript,
            last_response=self.context.last_response,
            history=self.context.history,
            goal_entities=goal_entities,
            active_app=self.context.active_app,
            active_website=self.context.active_website,
            last_search=self.context.last_search or None,
            current_media=self.context.current_media or None,
            previous_media=self.context.previous_media,
            last_action_info=self.context.last_action or None,
            conversation_turn=self.context.conversation_turn,
        )

    @staticmethod
    def _tool_succeeded(result) -> bool:
        """True when a tool result reports success (dict or ActionOutcome)."""
        if not result:
            return False
        if isinstance(result, dict):
            return bool(result.get("success"))
        if hasattr(result, "is_success"):
            return bool(result.is_success)
        if hasattr(result, "execution"):
            return getattr(result.execution, "status", None).name == "SUCCESS"
        return False

    def _record_tool_result(self, intent: Intent, result, res_list: list):
        """Stores tool output and updates structured working memory.

        Memory is updated ONLY on successful tool results — a failed step never
        fabricates media/search/action context (no false memory).
        """
        if not result:
            return
        self.context.last_tool_result = result
        if res_list:
            self.context.last_search_results = res_list

        if not self._tool_succeeded(result):
            return

        self.context.active_goal = intent.raw_text or self.context.last_transcript
        self.context.last_action = {
            "type": intent.action.name,
            "query": intent.target,
            "target": intent.target,
        }

        if intent.action == Action.OPEN_APP:
            self.context.last_opened_application = intent.target or ""
            self.context.active_app = intent.target or ""
        if intent.action == Action.OPEN_WEBSITE:
            self.context.last_opened_website = intent.target or ""
            self.context.active_website = intent.target or ""
        if intent.action in (Action.SEARCH_WEB, Action.PLAY_VIDEO) and intent.target:
            self.context.last_search_query = intent.target
            self.context.active_media = intent.target
        if self.context.current_goal:
            if intent.target:
                self.context.current_goal.entities["last_target"] = intent.target
            if res_list:
                self.context.current_goal.entities["search_results"] = res_list

        # ---- structured media / search evidence (tool-driven, no LLM) ----
        if intent.action == Action.PLAY_VIDEO:
            media = self._media_from_tool_result(intent.target, result)
            if media:
                if self.context.current_media:
                    self.context.previous_media.append(dict(self.context.current_media))
                    if len(self.context.previous_media) > 10:
                        self.context.previous_media.pop(0)
                self.context.current_media = media
                logger.info(
                    "[MEMORY] Current media updated: %s (%s)",
                    media.get("title") or media.get("query"), media.get("video_id") or "",
                )
        elif intent.action == Action.SEARCH_WEB:
            self.context.last_search = {
                "provider": "google",
                "query": intent.target,
                "results": res_list,
            }
            logger.info("[MEMORY] Search context updated: %r", (intent.target or "")[:60])
        logger.info("[MEMORY] Last action updated: %s(%s)", intent.action.name, intent.target or "")

    def _media_from_tool_result(self, target: str, result) -> dict:
        """Extract structured media evidence from a tool result (defaults empty)."""
        result_dict = result if isinstance(result, dict) else (
            result.execution.raw_tool_result if hasattr(result, "execution") and hasattr(result.execution, "raw_tool_result") else {}
        )
        if not isinstance(result_dict, dict):
            return {}
        provider = result_dict.get("provider") or "youtube"
        watch_url = result_dict.get("watch_url") or ""
        video_id = result_dict.get("video_id") or ""
        if not video_id and "watch?v=" in watch_url:
            video_id = watch_url.split("watch?v=", 1)[1].split("&", 1)[0]
        return {
            "provider": provider,
            "query": target,
            "title": result_dict.get("title") or "",
            "url": watch_url or result_dict.get("url") or "",
            "video_id": video_id,
        }

    def _intent_from_reasoned(self, reasoned: dict) -> Intent:
        conf = reasoned.get("confidence", _REASONER_CONF)
        if reasoned.get("action") not in Action._member_names_:
            raise KeyError(reasoned.get("action"))
        return Intent(
            action=Action[reasoned["action"]],
            target=reasoned.get("target", ""),
            arguments=reasoned.get("arguments", {}),
            intent_confidence=conf,
            target_confidence=conf,
        )

    def _reasoned_plan(self, reasoned: dict) -> tuple[Optional[ActionPlan], str]:
        """Builds + validates a reasoner-produced plan. (plan, "") or (None, error)."""
        conf = reasoned.get("confidence", _REASONER_CONF)
        steps = []
        for s in reasoned.get("steps", []):
            if s.get("action") not in Action._member_names_:
                return None, f"Plan contained an unknown action: {s.get('action')!r}"
            steps.append(Intent(
                action=Action[s["action"]],
                target=s.get("target", ""),
                arguments=s.get("arguments", {}),
                intent_confidence=conf,
                target_confidence=conf,
            ))
        plan = ActionPlan(steps=steps)
        perms = self.permissions if self.permissions else _DEFAULT_PERMS
        ok, reason = validate_plan(plan, perms)
        if not ok:
            return None, reason
        return plan, ""

    def _start_reasoned_plan(self, reasoned: dict) -> tuple[str, bool]:
        plan, err = self._reasoned_plan(reasoned)
        if err:
            return self._respond(err)
        self.context.current_plan = plan
        return self._continue_plan()

    def _respond(self, text: str) -> tuple[str, bool]:
        self.state_machine.transition_to(ConversationState.RESPONDING)
        self.state_machine.transition_to(ConversationState.LISTENING)
        self.context.last_response = text
        self.context.finalize_turn()
        self.context.push_turn()
        return text, True

    def _answer_memory_question(self, transcript: str) -> str:
        """Answer short-term memory questions directly from structured context.

        Returns a response string when the transcript is a recognised memory
        question and structured context contains the answer; otherwise "".
        """
        text = normalize(transcript).lower().strip("?!. ")
        if not text:
            return ""

        # "what did you just do?" — reconstruct from tool-driven context.
        if (
            "what" in text and any(word in text for word in ("did you just do", "did we just do", "did you do", "did we do", "have you done"))
        ):
            parts = []
            la = self.context.last_action
            if la:
                parts.append(
                    la.get("type", "")
                    .lower()
                    .replace("play_video", "played a video")
                    .replace("open_app", "opened an app")
                    .replace("open_website", "opened a website")
                    .replace("search_web", "searched the web")
                    .replace("_", " ")
                )
                if la.get("target"):
                    parts.append(la["target"])
            elif self.context.last_search_query:
                parts.append(f"searched for {self.context.last_search_query}")
            if parts:
                return "I " + " for ".join(parts) + "."
            if self.context.last_response:
                return f"I said: {self.context.last_response}"
            return "I haven't done anything yet in this conversation."

        # "what are we watching?" / "what video is playing?" / "what was playing"
        # / "what did you play" / "which video" / "what's playing"
        is_media_question = (
            "watching" in text
            or "playing" in text
            or ("what" in text and "video" in text)
            or ("which" in text and "video" in text)
            or ("what" in text and any(w in text for w in ("did you play", "did you just play")))
        )
        if is_media_question:
            media = self.context.current_media
            if media:
                title = media.get("title") or media.get("query")
                provider = media.get("provider", "youtube")
                return f"You're watching {title} on {provider}."
            if self.context.active_media:
                return f"We're on {self.context.active_media}."
            if self.context.last_search_query:
                return f"We were looking at {self.context.last_search_query}."
            return "I don't have a video in the current session."

        # "what did I ask you to search?" / "what was my last search?"
        if "ask" in text and "search" in text or ("last search" in text) or ("search for" in text and "did i" in text):
            query = (self.context.last_search or {}).get("query", "") or self.context.last_search_query
            if query:
                provider = (self.context.last_search or {}).get("provider", "youtube")
                return f"You asked me to search for {query} on {provider}."
            return "You haven't asked me to search for anything yet."

        return ""

    def _build_rag_context(self, resolved_text: str) -> str:
        """Retrieve RAG context for a chat turn; '' when disabled or degraded."""
        if not self.rag_service or not getattr(self.rag_service, "config", None):
            return ""
        if not self.rag_service.config.enabled:
            return ""
        if self._reasoner_supports_rag() is False:
            return ""
        try:
            history = [{"transcript": t.get("transcript", ""), "response": t.get("response", "")}
                       for t in (self.context.history or [])]
            result = self.rag_service.build_result(resolved_text, history=history)
            if result is None:
                return ""
            if result.no_context or not getattr(result, "final_context", None):
                logger.info(
                    "[RAG] query=%r no relevant context (gate %s) -> bare reasoning, "
                    "no injected block (P11)",
                    resolved_text[:120], getattr(result, "reason", "n/a"),
                )
                return ""
            return self.rag_service.build_prompt_block(result)
        except Exception as e:
            logger.warning("[RAG] Context build degraded: %s", e)
            return ""

    def _try_natural_conversation(self, transcript: str, cls) -> Optional[tuple]:
        """Answer pure conversational chatter locally, else return None.

        Runs after deterministic classification (free, no model) so commands,
        tool requests, context references and follow-ups are never stolen, and
        before context resolution / reasoner / RAG / research so a local
        response never costs an LLM call.
        """
        if not self.natural_conversation_enabled or self.natural_conversation_router is None:
            return None
        if cls in _NATURAL_CONVERSATION_SKIP_CLASSES:
            return None
        try:
            result = self.natural_conversation_router.route(transcript)
        except Exception as exc:  # never let the fast path break the pipeline
            logger.warning("[NATURAL_CHAT] disabled reason=error error=%s", exc)
            return None
        if result is None or not result.handled:
            return None
        self.context.active_question_type = "CONVERSATIONAL"
        return self._respond(result.response)

    def _conversational_ack(self, transcript: str) -> str:
        """Deterministic reply for pure chatter — no reasoner round-trip (P12)."""
        low = transcript.lower()
        if re.search(r"\b(thank|thanks)\b", low):
            return "You're welcome!"
        if re.search(r"\b(good\s*night|goodnight)\b", low):
            return "Good night! See you tomorrow."
        if re.search(r"\b(great|awesome|cool|perfect|amazing|helpful|good)\b", low):
            return "Glad I could help!"
        return "Got it. What else can I do?"

    def _extract_live_web_query(self, transcript: str) -> str:
        """
        Return a web-searchable query when *transcript* asks for CURRENT
        information (latest news / today / current weather / breaking updates),
        else "". Deterministic — no model call (P5).
        """
        low = transcript.lower().strip()
        m = _LIVE_WEB_PREFIX.match(low)
        if not m:
            return ""
        query = m.group(1).strip()
        if not query or len(query) < 2:
            return ""
        if _LIVE_WEB_LOCAL_FORBIDDEN.search(query):
            return ""
        return query

    def _try_research(self, transcript: str, st_context) -> Optional[tuple]:
        """Optionally run the research subsystem for *transcript*.

        Gated by ``research_enabled``. Returns a spoken reply when the research
        agent returned live evidence, otherwise None so the existing local
        pipeline handles the turn. Only surfaces evidence — never a synthesized
        answer (Phase 3+). Failures fall through silently to the reasoner.
        """
        if not self.research_enabled or not self.research_agent:
            return None
        try:
            ref = self.context.resolve_conversation_reference(
                transcript, st_context.history if st_context else None,
            )
            query = ref.resolved if ref.status == _REF_STATUS_RESOLVED else transcript
            self.context.activate_entity(ref.entity, ref.entity_type)
            query = self.context.rewrite_followup(query, st_context.history) or query
            response = self.research_agent.research(query)
        except Exception as exc:  # noqa: BLE001 - research is optional
            logger.warning("[RESEARCH] agent raised %s: %s", type(exc).__name__, exc)
            return None
        self.context.last_research = response
        if not response.needs_web or not response.success:
            return None
        top = response.results[:2]
        evidence = " ".join(f"{r.title} — {r.url}" for r in top)
        spoken = (
            f"I checked current sources and found {len(response.results)} "
            f"results. Top: {evidence}"
        )
        logger.info("[RESEARCH] surfacing %d results to user", len(response.results))
        return self._respond(spoken)

    def _reasoner_supports_rag(self) -> bool:
        """True when the reasoner's request() accepts retrieval_context."""
        if self._reasoner_rag_support is None:
            try:
                import inspect
                sig = inspect.signature(self.reasoner.request)
                self._reasoner_rag_support = "retrieval_context" in sig.parameters
            except (ValueError, TypeError):
                # Builtin / opaque callable: assume modern interface.
                self._reasoner_rag_support = True
        return self._reasoner_rag_support

    def _log_context(self, raw: str, ref: ReferenceResolution) -> None:
        """Structured [CONTEXT] log line for reference-resolution turns."""
        logger.info(
            "[CONTEXT] raw=%r resolved=%r status=%s entity=%s type=%s source=%s latency_ms=%.2f",
            raw, ref.resolved or raw, ref.status, ref.entity or "-",
            ref.entity_type or "-", ref.source or "-", ref.latency_ms,
        )
        if ref.status == _REF_STATUS_AMBIGUOUS:
            logger.info("[CONTEXT] candidates=%r clarification=%s", ref.candidates, ref.clarification)
        elif ref.clarification:
            logger.info("[CONTEXT] clarification=%s", ref.clarification)

    def _chat_response(self, resolved_text: str, st_context: ShortTermContext) -> tuple[str, bool]:
        """
        Reasoner CHAT mode for knowledge questions and casual conversation.
        Never routes simple deterministic commands through the model.
        """
        if self.reasoner and self.reasoner.is_available():
            try:
                retrieval_context = self._build_rag_context(resolved_text)
                if retrieval_context:
                    reasoned = self.reasoner.request(
                        resolved_text, st_context, mode="chat",
                        retrieval_context=retrieval_context,
                    )
                else:
                    reasoned = self.reasoner.request(resolved_text, st_context, mode="chat")
            except Exception as e:
                logger.error("[ERROR] Reasoning server unavailable: %s", e)
                return self._respond("Reasoning service unavailable.")

            r_type = reasoned.get("type")
            if r_type in ("response", "clarification"):
                text = reasoned.get("text") or reasoned.get("question") or "I didn't understand that."
                return self._respond(text)
            if r_type == "plan":
                return self._start_reasoned_plan(reasoned)
            if r_type == "intent":
                # Unexpected but safe: route through normal validated execution.
                try:
                    intent = self._intent_from_reasoned(reasoned)
                except KeyError:
                    return self._respond("I didn't understand that.")
                self.context.last_intent = intent
                policy = validate(intent)
                if policy == Policy.REJECT:
                    return self._respond("I didn't understand that.")
                if policy == Policy.CONFIRM:
                    if self.context.current_goal:
                        self.context.current_goal.state = GoalState.WAITING_FOR_USER
                    self.context.pending_intent = intent
                    self.context.confirmation_start_time = time.time()
                    self.state_machine.transition_to(ConversationState.WAITING_FOR_CONFIRMATION)
                    prompt = format_confirmation_prompt(intent)
                    self.context.last_response = prompt
                    return prompt, True
                return self._execute_single_intent(intent)
            return self._respond("I didn't understand that.")

        return self._respond("I didn't understand that. The reasoning model is unavailable right now.")

    def _execute_single_intent(self, intent: Intent) -> tuple[str, bool]:
        """Validated single-intent execution + context recording (SAFE policy)."""
        self.state_machine.transition_to(ConversationState.EXECUTING)
        result = registry.execute(
            intent,
            dry_run=self.dry_run,
            allow_real_execution=self.allow_real_execution,
            permissions=self.permissions,
        )
        res_list = _extract_results(result) if result else []
        self._record_tool_result(intent, result, res_list)
        if self.context.current_goal:
            self.context.current_goal.state = GoalState.COMPLETED
        response = result.get("spoken_message") or result.get("message", "Done.")
        return self._respond(response)

    def _continue_plan(self, is_resume: bool = False) -> tuple[str, bool]:
        """Runs the execution loop for the current plan."""
        plan = self.context.current_plan
        responses = []
        first_step = True

        if not self.context.current_goal:
            self.context.current_goal = GoalContext(
                objective=self.context.last_transcript,
                state=GoalState.IN_PROGRESS,
                active_plan=plan
            )
        else:
            self.context.current_goal.active_plan = plan
            self.context.current_goal.state = GoalState.IN_PROGRESS

        while plan.state in (PlanState.READY, PlanState.EXECUTING):
            if self.state_machine.current_state != ConversationState.EXECUTING:
                self.state_machine.transition_to(ConversationState.EXECUTING)

            if plan.current_step_index < len(plan.steps):
                step_intent = plan.steps[plan.current_step_index]
                self.context.last_intent = step_intent

            is_confirmed = is_resume and first_step
            response, requires_conf, is_completed, tool_result = execute_plan_step(
                plan, self.dry_run, self.allow_real_execution,
                is_confirmed=is_confirmed, permissions=self.permissions,
                goal_context=self.context.current_goal
            )
            first_step = False

            if response:
                responses.append(response)

            if tool_result:
                self.context.last_tool_result = tool_result
                self._record_tool_result(step_intent, tool_result, _extract_results(tool_result))
                if self.context.current_goal:
                    if step_intent.target:
                        self.context.current_goal.entities["last_target"] = step_intent.target
                    if step_intent.action == Action.SEARCH_WEB:
                        res_items = _extract_results(tool_result)
                        if res_items:
                            self.context.current_goal.entities["search_results"] = res_items

            if requires_conf:
                if self.context.current_goal:
                    self.context.current_goal.state = GoalState.WAITING_FOR_USER
                self.state_machine.transition_to(ConversationState.WAITING_FOR_CONFIRMATION)
                self.context.confirmation_start_time = time.time()
                self.context.last_response = " ".join(responses)
                return self.context.last_response, True

            if is_completed:
                break

        # Plan completed or failed
        if plan.state == PlanState.COMPLETED:
            if self.context.current_goal:
                self.context.current_goal.state = GoalState.COMPLETED
            self.context.current_plan = None
        elif plan.state in (PlanState.FAILED, PlanState.CANCELLED):
            if self.context.current_goal:
                self.context.current_goal.state = GoalState.FAILED
            self.context.current_plan = None

        final_response = " ".join(responses) if responses else "Done."

        self.state_machine.transition_to(ConversationState.RESPONDING)
        self.state_machine.transition_to(ConversationState.LISTENING)
        self.context.last_response = final_response
        self.context.push_turn()
        return final_response, True

    def handle_transcript(self, transcript: str) -> tuple[str, bool]:
        """
        Process a user transcript.

        Returns:
            (response_text, should_continue)
            where should_continue is False if state becomes STOPPING.
        """
        if not transcript or not transcript.strip():
            return "", True

        # Deterministic application/entity alias expansion for STT mishearings
        # ("can you open grom" -> "can you open chrome"). The normalized text is
        # what the whole pipeline routes on; the raw line is kept in the log.
        # Alias expansion is scoped to command-like utterances so a chat word
        # that happens to equal an app alias is never rewritten (P8).
        if _COMMAND_LIKE.search(transcript):
            alias_fixed, alias_changes = normalize_app_aliases(transcript)
            if alias_changes:
                logger.info(
                    "[QUERY_NORMALIZER] raw=%r normalized=%r changes=%r",
                    transcript, alias_fixed, alias_changes,
                )
                transcript = alias_fixed

        # Session lifecycle: expire the active session after user inactivity,
        # then refresh the inactivity timer on every processed interaction.
        self._check_session_expiry()
        self.session.touch()
        self.context.last_transcript = transcript
        self.context.last_raw_query = transcript
        self.context.last_resolved_query = ""
        self.context.last_resolution_status = _REF_STATUS_NOT_NEEDED
        self.context.update_topic(transcript)
        self.context.observe_turn(transcript)
        norm_trans = normalize(transcript)

        # Priority 0: Explicit session end — exit active conversation, keep running.
        if norm_trans in ("go to sleep", "stop listening", "end session", "go idle", "sleep"):
            response = self._end_session_soft()
            st = self.state_machine.current_state
            if st == ConversationState.STOPPING:
                self.state_machine.transition_to(ConversationState.IDLE)
            if st in (ConversationState.IDLE, ConversationState.STOPPING):
                self.state_machine.transition_to(ConversationState.LISTENING)
            if self.state_machine.current_state == ConversationState.LISTENING:
                self.state_machine.transition_to(ConversationState.PROCESSING)
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = response
            return response, True

        # Priority 1 & 2: Global System Commands (Stop & Cancel).
        # All exit variants (bye / good bye / see you / that's all / shutdown /
        # stop friday) resolve deterministically here — never to the reasoner.
        if norm_trans in _EXIT_UTTERANCES:
            self.session.end()
            self.context.pending_intent = None
            if self.context.current_plan:
                self.context.current_plan.state = PlanState.CANCELLED
                self.context.current_plan = None
            self.state_machine.transition_to(ConversationState.STOPPING)
            self.context.last_response = "Goodbye."
            return "Goodbye.", False

        if norm_trans in ("cancel", "never mind", "nevermind", "abort"):
            self.context.pending_intent = None
            if self.context.current_plan:
                self.context.current_plan.state = PlanState.CANCELLED
                self.context.current_plan = None

            if self.state == ConversationState.LISTENING:
                self.state_machine.transition_to(ConversationState.PROCESSING)
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = "Cancelled."
            return "Cancelled.", True

        # Ensure active listening state for incoming commands
        if self.state == ConversationState.STOPPING:
            self.state_machine.transition_to(ConversationState.IDLE)
        if self.state == ConversationState.IDLE:
            self.state_machine.transition_to(ConversationState.LISTENING)

        # ------------------------------------------------------------------
        # State: WAITING_FOR_CONFIRMATION
        # ------------------------------------------------------------------
        if self.state == ConversationState.WAITING_FOR_CONFIRMATION:
            if time.time() - self.context.confirmation_start_time > 30.0:
                logger.info("Confirmation timeout expired. Resetting state.")
                self.context.pending_intent = None
                if self.context.current_plan:
                    self.context.current_plan.state = PlanState.CANCELLED
                    self.context.current_plan = None
                self.state_machine.transition_to(ConversationState.LISTENING)
                # Fall through to treat the current transcript as a new command
            else:
                confirmed = parse_confirmation_response(transcript)

                if confirmed is True:
                    # If we have an active plan, resume it.
                    if self.context.current_plan and self.context.current_plan.state == PlanState.WAITING_FOR_CONFIRMATION:
                        self.context.current_plan.state = PlanState.EXECUTING
                        return self._continue_plan(is_resume=True)

                    # Otherwise, it's a single intent confirmation
                    pending = self.context.pending_intent
                    self.context.pending_intent = None
                    self.state_machine.transition_to(ConversationState.EXECUTING)

                    result = registry.execute(
                        pending,
                        dry_run=self.dry_run,
                        allow_real_execution=self.allow_real_execution,
                        permissions=self.permissions,
                    )
                    if result:
                        self.context.last_tool_result = result
                        raw_dict = result.raw_tool_result if hasattr(result, "raw_tool_result") and isinstance(result.raw_tool_result, dict) else (result if isinstance(result, dict) else {})
                        if raw_dict.get("results"):
                            self.context.last_search_results = raw_dict.get("results")
                        res_list = _extract_results(result)
                        self._record_tool_result(pending, result, res_list)

                    if self.context.current_goal:
                        self.context.current_goal.state = GoalState.COMPLETED

                    self.state_machine.transition_to(ConversationState.RESPONDING)
                    self.state_machine.transition_to(ConversationState.LISTENING)
                    self.context.last_response = result.get("spoken_message") or result.get("message", "Done.")
                    self.context.push_turn()
                    return self.context.last_response, True

                elif confirmed is False:
                    self.context.pending_intent = None
                    if self.context.current_plan:
                        self.context.current_plan.state = PlanState.CANCELLED
                        self.context.current_plan = None

                    # If user said "no, <new command>", process new transcript
                    if len(transcript.strip().split()) > 1 and not transcript.strip().lower() in ("no", "cancel", "never mind", "nevermind", "abort", "n"):
                        self.state_machine.transition_to(ConversationState.PROCESSING)
                        st_text = transcript.strip()
                        if st_text.lower().startswith("no, "):
                            st_text = st_text[4:].strip()
                        resolved_text, err = resolve_context(st_text, self._get_short_term_context())
                        if not err:
                            intent = route(resolved_text)
                            if intent.action != Action.UNKNOWN:
                                self.context.last_intent = intent
                                policy = validate(intent)
                                if policy == Policy.SAFE:
                                    self.state_machine.transition_to(ConversationState.EXECUTING)
                                    result = registry.execute(
                                        intent, dry_run=self.dry_run,
                                        allow_real_execution=self.allow_real_execution,
                                        permissions=self.permissions
                                    )
                                    if isinstance(result, dict) and result.get("results"):
                                        self.context.last_search_results = result.get("results")
                                    self.context.last_tool_result = result
                                    self.state_machine.transition_to(ConversationState.RESPONDING)
                                    self.state_machine.transition_to(ConversationState.LISTENING)
                                    self.context.last_response = result.get("spoken_message") or result.get("message", "Done.")
                                    self.context.push_turn()
                                    return self.context.last_response, True

                    self.state_machine.transition_to(ConversationState.RESPONDING)
                    self.state_machine.transition_to(ConversationState.LISTENING)
                    self.context.last_response = "Cancelled."
                    self.context.push_turn()
                    return "Cancelled.", True

                routed = route(transcript)
                if routed.action != Action.UNKNOWN:
                    response = "You have a pending confirmation. Say yes, no, or cancel."
                    self.context.last_response = response
                    return response, True

                response = "Please say yes, no, or cancel."
                self.context.last_response = response
                return response, True


        # ------------------------------------------------------------------
        # Normal State: LISTENING -> PROCESSING
        # ------------------------------------------------------------------
        self.state_machine.transition_to(ConversationState.PROCESSING)
        st_context = self._get_short_term_context()

        # Deterministic request classification (no LLM).
        cls = log_class(transcript, classify(transcript))

        # Natural Conversation Layer: pure chatter ("hi", "how are you?",
        # "thanks", "nice") is answered locally, before context resolution and
        # before any reasoner / RAG / research / browser work. Utterances that
        # carry a substantive request are declined here and continue down the
        # normal pipeline unchanged.
        natural = self._try_natural_conversation(transcript, cls)
        if natural is not None:
            return natural

        # Screen / vision question — truthful: we have no screen access.
        if cls == RequestClass.SCREEN_QUESTION:
            return self._respond("I don't currently have access to your screen.")

        # Casual chatter ("thanks", "okay", "you're great", "good night").
        # A deterministic acknowledgment, never the 30s reasoner (P12).
        if cls == RequestClass.CONVERSATIONAL:
            return self._respond(self._conversational_ack(transcript))

        # Knowledge question / casual chat -> reasoner CHAT mode, unless the
        # deterministic router already knows a concrete command (time, memory)
        # or the request asks for CURRENT information that only a live web
        # search can answer (P5). Informational follow-ups ("tell me more about
        # him", "who is the president") classify as FOLLOW_UP/QUESTION and
        # belong on this chat path, never on ACTION (R3). UNKNOWN is
        # deliberately excluded: it is the residual bucket for command
        # near-misses ("open grove") and noise, which must stay off the model
        # path (fuzzy-router latency contract).
        if cls in (RequestClass.QUESTION, RequestClass.CHAT,
                   RequestClass.FOLLOW_UP):
            self.context.active_question_type = getattr(cls, "name", str(cls))
            memory_answer = self._answer_memory_question(transcript)
            if memory_answer:
                return self._respond(memory_answer)
            live_query = self._extract_live_web_query(transcript)
            if live_query:
                live_intent = route(f"search for {live_query}")
                if live_intent.action == Action.SEARCH_WEB:
                    if validate(live_intent) != Policy.SAFE:
                        live_query = None
                    else:
                        self.context.last_intent = live_intent
                        self.context.live_topic = live_query.rstrip("?!. ")
                        logger.info(
                            "[LIVE_WEB] current-information query %r -> SEARCH_WEB(%r)",
                            transcript, live_query,
                        )
                        return self._execute_single_intent(live_intent)
            if not live_query:
                research_reply = self._try_research(transcript, st_context)
                if research_reply is not None:
                    return research_reply
            early_intent = route(transcript)
            if early_intent.action == Action.UNKNOWN or early_intent.confidence < 0.75:
                ref = self.context.resolve_conversation_reference(transcript, st_context.history)
                self._log_context(transcript, ref)
                if ref.status == _REF_STATUS_AMBIGUOUS:
                    return self._respond(ref.clarification)
                if ref.status == _REF_STATUS_UNRESOLVED:
                    return self._respond(ref.clarification)
                # Live-web bridging: a turn that moves the focus away from an
                # active live-info thread stays on the current-information path
                # (P5-style), e.g. "latest news about Russia" -> "what about
                # Ukraine" or "tell me more about the UK".
                if (self.context.live_topic and ref.entity
                        and ref.entity != self.context.live_topic):
                    live_lq = f"latest news about {ref.entity}"
                    live_intent = route(f"search for {live_lq}")
                    if live_intent.action == Action.SEARCH_WEB and validate(live_intent) == Policy.SAFE:
                        self.context.last_intent = live_intent
                        self.context.live_topic = ref.entity
                        logger.info(
                            "[LIVE_WEB] reference follow-up %r -> SEARCH_WEB(%r)",
                            transcript, live_lq,
                        )
                        return self._execute_single_intent(live_intent)
                if ref.status == _REF_STATUS_RESOLVED:
                    resolved_text = ref.resolved
                    self.context.activate_entity(ref.entity, ref.entity_type)
                else:
                    resolved_text = transcript
                if not resolved_text:
                    resolved_text = ref.resolved or transcript
                resolved_text, _ = resolve_context(resolved_text, st_context)
                if not resolved_text:
                    resolved_text = transcript
                # Rewrite conversational follow-ups into standalone queries
                # (e.g. "Why did we use it?" → "Why did Friday use faster-whisper?")
                resolved_text = self.context.rewrite_followup(resolved_text, st_context.history)
                if not resolved_text:
                    resolved_text = transcript
                self.context.last_resolved_query = resolved_text
                self.context.last_resolution_status = ref.status
                return self._chat_response(resolved_text, st_context)

        # Check if multi-step planner is needed
        if cls == RequestClass.COMMAND or " and " in transcript or " then " in transcript:
            plan, err = parse_plan(transcript, st_context)
            if not err:
                # Phase 8: validate the ENTIRE plan before any step executes
                effective_perms = self.permissions if self.permissions else _DEFAULT_PERMS
                plan_ok, plan_reason = validate_plan(plan, effective_perms)
                if not plan_ok:
                    self.state_machine.transition_to(ConversationState.RESPONDING)
                    self.state_machine.transition_to(ConversationState.LISTENING)
                    self.context.last_response = plan_reason
                    return plan_reason, True
                self.context.current_plan = plan
                return self._continue_plan()

            # If deterministic planner fails, fall through to single-step/reasoner
            # We don't return the err immediately.
            resolved_text = transcript
        else:
            resolved_text, err = resolve_context(transcript, st_context)
            if err:
                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                self.context.last_response = err
                return err, True

        low_trans = transcript.lower().strip()
        is_correction = self.context.last_intent and (
            low_trans.startswith("no, i meant ") or low_trans.startswith("i meant ") or
            low_trans.startswith("no, the ") or low_trans.startswith("no, search ") or
            low_trans.startswith("no, ")
        )
        if is_correction:
            corr_target = low_trans.replace("no, i meant ", "").replace("i meant ", "").replace("no, search ", "").replace("no, ", "").strip()
            if corr_target.endswith(" instead"):
                corr_target = corr_target[:-8].strip()
            resolved_text, _ = resolve_context(corr_target, st_context)
            intent = route(resolved_text)
            if intent.action == Action.UNKNOWN or intent.confidence < 0.85:
                act = self.context.last_intent.action
                if act == Action.SEARCH_WEB:
                    resolved_text = f"search for {corr_target}"
                elif act == Action.OPEN_WEBSITE:
                    resolved_text = f"go to {corr_target}"
                elif act == Action.READ_WEBSITE:
                    resolved_text = f"read {corr_target}"
                elif act == Action.OPEN_APP:
                    resolved_text = f"open {corr_target}"
                elif act == Action.CLOSE_APP:
                    resolved_text = f"close {corr_target}"
                elif act == Action.FIND_FILE:
                    resolved_text = f"find file {corr_target}"
                else:
                    resolved_text = corr_target
                intent = route(resolved_text)
        else:
            intent = route(resolved_text)

        # --- Local Reasoner Fallback Gate ---
        call_reasoner, gating_reason = should_call_reasoner(
            resolved_text,
            intent,
            is_in_confirmation=(self.state == ConversationState.WAITING_FOR_CONFIRMATION),
        )
        if call_reasoner and self.reasoner and self.reasoner.is_available():
            logger.info("[REASONER] %s -> invoking reasoner layer", gating_reason)
            # Conversational reference resolution for unclassified / context-reference
            # turns ("tell me more about him", "who is he") before the local model.
            ref = self.context.resolve_conversation_reference(
                resolved_text or transcript, st_context.history,
            )
            self._log_context(resolved_text or transcript, ref)
            if ref.status == _REF_STATUS_AMBIGUOUS:
                return self._respond(ref.clarification)
            if ref.status == _REF_STATUS_UNRESOLVED:
                return self._respond(ref.clarification)
            if ref.status == _REF_STATUS_RESOLVED:
                resolved_text = ref.resolved
                self.context.last_resolved_query = resolved_text
                self.context.last_resolution_status = ref.status
                self.context.activate_entity(ref.entity, ref.entity_type)
            try:
                # Informational / unclassified phrasing always goes to the
                # reasoner in CHAT mode. Mode=action would send a bare natural-
                # language sentence to the ACTION structured parser and yield a
                # mismatched spuriously-parsed "action" (R3).
                reasoned = self.reasoner.request(resolved_text, st_context, mode="chat")
            except Exception as e:
                logger.error("[ERROR] Reasoning server unavailable: %s", e)
                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                err_msg = "Reasoning service unavailable."
                self.context.last_response = err_msg
                self.context.push_turn()
                return err_msg, True

            r_type = reasoned.get("type")

            if r_type == "plan":
                return self._start_reasoned_plan(reasoned)

            elif r_type == "intent":
                intent = self._intent_from_reasoned(reasoned)

            elif r_type in ("response", "clarification"):
                text = reasoned.get("text") or reasoned.get("question") or "I didn't understand that."
                return self._respond(text)

        # --- End Reasoner Fallback ---

        self.context.last_intent = intent

        if intent.action != Action.UNKNOWN:
            logger.info(
                "[ROUTER] Deterministic route selected: %s target=%r",
                intent.action.name, intent.target,
            )

        if intent.action == Action.SYSTEM_HELP:
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = _HELP_TEXT
            return _HELP_TEXT, True

        if intent.action == Action.SYSTEM_REPEAT:
            response = self.context.last_response or "I haven't said anything yet."
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            return response, True

        if intent.action == Action.SYSTEM_CANCEL:
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = "Cancelled."
            self.context.pending_intent = None
            self.context.current_plan = None
            self.context.current_goal = None
            return "Cancelled.", True

        if intent.action == Action.SYSTEM_STOP:
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = "Stopped."
            return "Stopped.", True

        # Safety Validation
        policy = validate(intent)

        if policy == Policy.REJECT:
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            response = "I didn't understand that."
            self.context.last_response = response
            self.context.push_turn()
            return response, True

        if not self.context.current_goal:
            self.context.current_goal = GoalContext(objective=transcript, state=GoalState.IN_PROGRESS)

        if policy == Policy.CONFIRM:
            if self.context.current_goal:
                self.context.current_goal.state = GoalState.WAITING_FOR_USER
            self.context.pending_intent = intent
            self.context.confirmation_start_time = time.time()
            self.state_machine.transition_to(ConversationState.WAITING_FOR_CONFIRMATION)
            prompt = format_confirmation_prompt(intent)
            self.context.last_response = prompt
            return prompt, True

        # Policy: SAFE
        return self._execute_single_intent(intent)
