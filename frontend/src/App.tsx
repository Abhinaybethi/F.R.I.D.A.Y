import { Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { AgentsPage } from "./pages/AgentsPage";
import { AutomationPage } from "./pages/AutomationPage";
import { ChatPage } from "./pages/ChatPage";
import { CodePage } from "./pages/CodePage";
import { HomePage } from "./pages/HomePage";
import { ImagePage } from "./pages/ImagePage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { ModelsPage } from "./pages/ModelsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ResearchPage } from "./pages/ResearchPage";
import { SettingsPage } from "./pages/SettingsPage";
import { VisionPage } from "./pages/VisionPage";
import { VoicePage } from "./pages/VoicePage";
import { WorkspacePage } from "./pages/WorkspacePage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/voice" element={<VoicePage />} />
        <Route path="/vision" element={<VisionPage />} />
        <Route path="/image" element={<ImagePage />} />
        <Route path="/research" element={<ResearchPage />} />
        <Route path="/code" element={<CodePage />} />
        <Route path="/automation" element={<AutomationPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/workspace" element={<WorkspacePage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
