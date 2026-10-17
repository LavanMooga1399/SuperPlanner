import { Link, useParams } from "react-router";
import { NotFound } from "../App";
import { listTemplates } from "../api/client";
import { ErrorBanner, Loading } from "../components/Banner";
import { Icon } from "../components/Icon";
import { TemplateCard } from "../components/TemplateCard";
import { DisclaimerBanner, DisclaimerDialog } from "../finance/components/DisclaimerBanner";
import { FinanceTemplateCards } from "../finance/components/FinanceTemplateCards";
import "../finance/finance.css";
import { useAsync } from "../lib/useAsync";
import { KINDS, isPlanKind, type KindInfo } from "./kinds";

function SchedulingExample({ info }: { info: KindInfo }) {
  const templates = useAsync((s) => listTemplates(s), []);
  if (templates.loading && !templates.data) return <Loading label="Loading the example…" />;
  if (templates.error) return <ErrorBanner error={templates.error} onRetry={templates.reload} />;
  const tpl = (templates.data?.items ?? []).find((t) => t.id === info.templateId);
  if (!tpl)
    return (
      <div className="empty">
        <Icon name="help" size={28} />
        <p>This server has no example for this kind of plan. Start from one of the other ways instead.</p>
        <Link className="btn" to={`/new/${info.kind}`}>
          Other ways to start
        </Link>
      </div>
    );
  return (
    <div className="grid-3">
      <TemplateCard template={tpl} />
    </div>
  );
}

/** `/new/:kind/example` (PHASE2.md 3.1): the matching scheduling template, or the finance example cards. */
export function ExamplePage() {
  const { kind } = useParams();
  if (!isPlanKind(kind)) return <NotFound />;
  const info = KINDS[kind];
  return (
    <div className="col gap-lg">
      {info.scheduling ? null : <DisclaimerBanner compact />}
      <nav aria-label="Breadcrumb" className="small">
        <Link to={`/new/${kind}`}>
          <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> Other ways to start
        </Link>
      </nav>
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div>
          <h1>Start from an example</h1>
          <p>
            {info.scheduling
              ? "The example is filled in for you. Adjust it under Options, create it, then change anything you like."
              : "Examples come with sensible defaults; you can change everything in the next steps."}
          </p>
        </div>
      </div>
      {info.scheduling ? <SchedulingExample info={info} /> : <FinanceTemplateCards />}
      {info.scheduling ? null : <DisclaimerDialog />}
    </div>
  );
}
