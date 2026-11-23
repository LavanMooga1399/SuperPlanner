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
import { PageHeader } from "../components/PageHeader";
import { t, t as tr } from "../lib/i18n";

function SchedulingExample({ info }: { info: KindInfo }) {
  const templates = useAsync((s) => listTemplates(s), []);
  if (templates.loading && !templates.data) return <Loading label={t("studio.examplePage.label.loadingTheExample")} />;
  if (templates.error) return <ErrorBanner error={templates.error} onRetry={templates.reload} />;
  const tpl = (templates.data?.items ?? []).find((t) => t.id === info.templateId);
  if (!tpl)
    return (
      <div className="empty">
        <Icon name="help" size={28} />
        <p>{t("studio.examplePage.text.thisServerHasNoExample")}</p>
        <Link className="btn" to={`/new/${info.kind}`}>
          {t("studio.examplePage.btn.otherWaysToStart")}
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
      <nav aria-label={t("studio.examplePage.aria.breadcrumb")} className="small">
        <Link to={`/new/${kind}`}>
          <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> {t("studio.examplePage.btn.otherWaysToStart")}
        </Link>
      </nav>
      <PageHeader
        title={t("studio.examplePage.title.startFromAnExample")}
        description={
          info.scheduling
            ? tr("studio.examplePage.str.theExampleIsFilledIn")
            : tr("studio.examplePage.str.examplesComeWithSensibleDefaults")
        }
      />
      {info.scheduling ? <SchedulingExample info={info} /> : <FinanceTemplateCards />}
      {info.scheduling ? null : <DisclaimerDialog />}
    </div>
  );
}
