import { Link } from "react-router-dom";

import { Icon } from "../components/Icon";

export function NotFoundPage() {
  return (
    <div className="page">
      <section className="panel center" style={{ padding: 48 }}>
        <span className="eyebrow">404</span>
        <h1 style={{ margin: "8px 0" }}>This surface does not exist</h1>
        <p className="dim" style={{ maxWidth: "52ch", margin: "0 auto 18px" }}>
          The dashboard only routes to real pages. Use the navigation to return to a working surface.
        </p>
        <Link to="/" className="btn btn-primary">
          <Icon name="home" size={14} /> Back to Home
        </Link>
      </section>
    </div>
  );
}
