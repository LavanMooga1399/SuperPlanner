/**
 * Manufacturing routes (M 11.1), spread into the existing `App` children inside `RequireAuth` next to the
 * finance routes. The health "Fix" links of M 11.3 resolve to these patterns exactly.
 */
import type { ReactElement } from "react";
import { Navigate, useParams, type RouteObject } from "react-router";
import "./mfg.css";
import { MfgLayout, MfgNotFound } from "./pages/MfgLayout";
import { MfgHome } from "./pages/MfgHome";
import { ItemsPage } from "./pages/ItemsPage";
import { ItemShell } from "./pages/ItemShell";
import { ItemDetailsTab } from "./pages/ItemDetailsTab";
import { BomTab } from "./pages/BomTab";
import { BomEditPage } from "./pages/BomEditPage";
import { WhereUsedTab } from "./pages/WhereUsedTab";
import { RoutingTab } from "./pages/RoutingTab";
import { PlantLayout } from "./pages/PlantLayout";
import { GroupsPage } from "./pages/GroupsPage";
import { ShiftsPage } from "./pages/ShiftsPage";
import { CalendarPage } from "./pages/CalendarPage";
import { PlantSettingsPage } from "./pages/PlantSettingsPage";
import { ResourcesLayout } from "./pages/ResourcesLayout";
import { SkillsPage } from "./pages/SkillsPage";
import { OperatorsPage } from "./pages/OperatorsPage";
import { ToolingPage } from "./pages/ToolingPage";
import { HealthPage } from "./pages/HealthPage";
import { ImportWizard } from "./pages/ImportWizard";
import { ItemStockTab } from "./pages/ItemStockTab";
import { ItemSuppliersTab } from "./pages/ItemSuppliersTab";
import { InventoryLayout } from "./pages/inventory/InventoryLayout";
import { BalancesTab } from "./pages/inventory/BalancesTab";
import { TransactionsTab } from "./pages/inventory/TransactionsTab";
import { PostingPage } from "./pages/inventory/PostingPage";
import { PostingForm } from "./pages/inventory/PostingForm";
import { LotsTab } from "./pages/inventory/LotsTab";
import { LocationsTab } from "./pages/inventory/LocationsTab";
import { PurchasingLayout } from "./pages/purchasing/PurchasingLayout";
import { PurchaseDocList } from "./pages/purchasing/PurchaseDocList";
import { PurchaseDocRoute } from "./pages/purchasing/PurchaseDocPage";
import { DeliveryBoard } from "./pages/purchasing/DeliveryBoard";
import { SupplierPage, SuppliersPage } from "./pages/purchasing/SuppliersPage";
import { DemandList } from "./pages/demand/DemandList";
import { DemandPage } from "./pages/demand/DemandPage";
import { WorkOrderList } from "./pages/workorders/WorkOrderList";
import { WorkOrderPage } from "./pages/workorders/WorkOrderPage";
import { KittingCheckPage } from "./pages/workorders/KittingCheckPage";
import { MrpRunsPage } from "./pages/mrp/MrpRunsPage";
import { RunShell } from "./pages/mrp/RunShell";
import { RunSummaryTab } from "./pages/mrp/RunSummaryTab";
import { RunItemsTab } from "./pages/mrp/RunItemsTab";
import { ItemPlanPage } from "./pages/mrp/ItemPlanPage";
import { PlannedOrdersTab } from "./pages/mrp/PlannedOrdersTab";
import { ExceptionsTab } from "./pages/mrp/ExceptionsTab";
import { DemandProjectionTab } from "./pages/mrp/DemandProjectionTab";
import { PeggingPage } from "./pages/mrp/PeggingPage";
import { CompareView } from "./pages/mrp/CompareView";
import { ShortagesPage } from "./pages/ShortagesPage";
import { MembersPage } from "./pages/MembersPage";
import { SetupMatrixPage } from "./pages/SetupMatrixPage";
import { ApsRunsPage } from "./pages/schedule/ApsRunsPage";
import { ApsRunShell } from "./pages/schedule/ApsRunShell";
import { ApsSummaryTab } from "./pages/schedule/ApsSummaryTab";
import { ApsGanttTab } from "./pages/schedule/ApsGanttTab";
import { ApsLoadTab } from "./pages/schedule/ApsLoadTab";
import { ApsDispatchTab } from "./pages/schedule/ApsDispatchTab";
import { ApsDemandTab, ApsOrdersTab } from "./pages/schedule/ApsOrdersTab";
import { ApsOvertimeTab } from "./pages/schedule/ApsOvertimeTab";
import { ApsExceptionsTab } from "./pages/schedule/ApsExceptionsTab";
import { ApsCompareTab } from "./pages/schedule/ApsCompareTab";

import { AuditPage } from "./pages/m5/AuditPage";
import { EcoListPage, EcoPage } from "./pages/m5/EcoPages";
import { IntegrationLayout, IntegrationOverview, IntegrationSettingsTab } from "./pages/m5/IntegrationPages";
import { BatchPage, BatchesTab, DeliveriesTab, EndpointsTab, EventsTab, FiledropTab, PlantTokensTab, ReconciliationPage, ReconciliationTab, ValueMapsTab } from "./pages/m5/IntegrationPages2";
import { RecallPage, RecallsPage } from "./pages/m5/RecallPages";
import { TracePage, WhereUsedPage } from "./pages/m5/TracePages";
import { TransferPage, TransfersPage } from "./pages/m5/TransferPages";
import { DashboardPage } from "./pages/m6/DashboardPage";
import { Part11ExportsPage, Part11Page, PoliciesPage } from "./qa/Part11Pages";
import { HoldsPage, InspectionLotPage, InspectionLotsPage } from "./qa/InspectionPages";
import { PlanPage, PlansPage, QaSettingsPage, SchemePage, SchemesPage } from "./qa/PlanPages";
import { FloorInspect } from "./qa/FloorInspect";
import { NcrPage, NcrsPage } from "./qa/NcrPages";
import { CapaPage, CapasPage, ComplaintPage, ComplaintsPage } from "./qa/CapaPages";
import { FieldActionPage, FieldActionsPage } from "./qa/FieldActionPages";
import { EquipmentListPage, EquipmentPage } from "./qa/EquipmentPages";
import { PrintRecordPage } from "./qa/PrintRecord";
import { ForecastPage } from "./forecast/ForecastPage";
import { AccuracyPage } from "./forecast/AccuracyPage";
import { InvoptPage } from "./invopt/InvoptPage";
import { ItemPackagingTab, ItemPlanningTab } from "./invopt/ItemPlanningTabs";
import { KanbanCardsPrint, KanbanPage } from "./kanban/KanbanPage";
import { RateRunPage, RateRunsPage } from "./rate/RatePages";
import { SterilisationPage } from "./ster/SterilisationPage";
import { ValidationPage } from "./validation/ValidationPage";
import { NetworkHome } from "./network/NetworkHome";
import { NetRunPage } from "./network/NetRunPage";
import { SourcingPage } from "./network/SourcingPage";
import { SopCyclesPage } from "./sop/SopCyclesPage";
import { SopCyclePage } from "./sop/SopCyclePage";
import { ScenarioPage } from "./sop/ScenarioPage";
import { MpsPage } from "./sop/MpsPage";
import { ItemTradeTab } from "./trade/TradeBits";
import { TradePage } from "./trade/TradePage";
import { TradeReportPage } from "./trade/TradeReportPage";
import { SourcingRiskPage } from "./trade/SourcingRiskPage";
import { useAccess } from "./lib/permissions";
import { FloorBatch } from "./floor/FloorBatch";
import { FloorDowntime } from "./floor/FloorDowntime";
import { FloorHome } from "./floor/FloorHome";
import { FloorLayout } from "./floor/FloorLayout";
import { FloorOperation } from "./floor/FloorOperation";
import { FloorQueue } from "./floor/FloorQueue";
import { FloorWo } from "./floor/FloorWo";
import { FloorEvents } from "./pages/m4/FloorEvents";
import { FloorOverview } from "./pages/m4/FloorOverview";
import { KpiPage } from "./pages/m4/KpiPage";
import { LabelsPage, TravellerPage } from "./pages/m4/PrintPages";
import { ReplanPage } from "./pages/m4/ReplanPage";
import { SerialPage, SerialsPage } from "./pages/m4/SerialsPage";
import { SimulationPage, SimulationsPage } from "./pages/m4/SimulationsPage";

/** A fresh page instance per document id (no state carried from one document to the next). */
function Keyed({ param, children }: { param: string; children: (key: string) => ReactElement }) {
  const params = useParams();
  return children(params[param] ?? "");
}

/** M9 10: the network workspace opens on its network home; plants keep the overview. */
function MfgIndex() {
  const { isNetwork } = useAccess();
  return isNetwork ? <Navigate to="/mfg/network" replace /> : <MfgHome />;
}

export const mfgRoutes: RouteObject[] = [
  // ---------------------------------------------------------------- M4 floor (12): tablet shell without the mfg nav
  {
    path: "mfg/floor",
    element: <FloorLayout />,
    children: [
      { index: true, element: <FloorHome /> },
      { path: "lines/:lineId", element: <Keyed param="lineId">{(k) => <FloorQueue key={k} />}</Keyed> },
      { path: "lines/:lineId/downtime", element: <FloorDowntime /> },
      { path: "lines/:lineId/batch", element: <FloorBatch /> },
      { path: "ops/:woOpId", element: <Keyed param="woOpId">{(k) => <FloorOperation key={k} />}</Keyed> },
      // the server's scan links (#200 `link`) use this form
      { path: "operations/:woOpId", element: <Keyed param="woOpId">{(k) => <FloorOperation key={k} />}</Keyed> },
      { path: "wo/:woId", element: <FloorWo /> },
      // M7 10: results entry on the tablet
      { path: "inspect/:lotId", element: <Keyed param="lotId">{(k) => <FloorInspect key={k} />}</Keyed> },
    ],
  },
  {
    path: "mfg",
    element: <MfgLayout />,
    children: [
      { index: true, element: <MfgIndex /> },
      { path: "items", element: <ItemsPage /> },
      {
        path: "items/:itemId",
        element: <ItemShell />,
        children: [
          { index: true, element: <ItemDetailsTab /> },
          { path: "bom", element: <BomTab /> },
          { path: "bom/:bomId/edit", element: <BomEditPage /> },
          { path: "where-used", element: <WhereUsedTab /> },
          { path: "routing", element: <RoutingTab /> },
          { path: "stock", element: <ItemStockTab /> },
          { path: "suppliers", element: <ItemSuppliersTab /> },
          { path: "planning", element: <ItemPlanningTab /> },
          { path: "packaging", element: <ItemPackagingTab /> },
          { path: "trade", element: <ItemTradeTab /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      {
        path: "plant",
        element: <PlantLayout />,
        children: [
          { index: true, element: <Navigate to="groups" replace /> },
          { path: "groups", element: <GroupsPage /> },
          { path: "shifts", element: <ShiftsPage /> },
          { path: "calendar", element: <CalendarPage /> },
          { path: "settings", element: <PlantSettingsPage /> },
          { path: "setups", element: <SetupMatrixPage /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      {
        path: "resources",
        element: <ResourcesLayout />,
        children: [
          { index: true, element: <Navigate to="skills" replace /> },
          { path: "skills", element: <SkillsPage /> },
          { path: "operators", element: <OperatorsPage /> },
          { path: "tooling", element: <ToolingPage /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      { path: "health", element: <HealthPage /> },
      { path: "import", element: <ImportWizard /> },
      { path: "import/:importId", element: <ImportWizard /> },
      // ---------------------------------------------------------------- M2 (14.2)
      {
        path: "inventory",
        element: <InventoryLayout />,
        children: [
          { index: true, element: <BalancesTab /> },
          { path: "transactions", element: <TransactionsTab /> },
          { path: "postings/:postingId", element: <PostingPage /> },
          { path: "post", element: <PostingForm /> },
          { path: "lots", element: <LotsTab /> },
          { path: "locations", element: <LocationsTab /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      {
        path: "purchasing",
        element: <PurchasingLayout />,
        children: [
          { index: true, element: <Navigate to="orders" replace /> },
          { path: "orders", element: <PurchaseDocList docType="po" /> },
          { path: "orders/:docId", element: <PurchaseDocRoute docType="po" /> },
          { path: "requests", element: <PurchaseDocList docType="pr" /> },
          { path: "requests/:docId", element: <PurchaseDocRoute docType="pr" /> },
          { path: "schedule", element: <DeliveryBoard /> },
          { path: "suppliers", element: <SuppliersPage /> },
          { path: "suppliers/:supplierId", element: <SupplierPage /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      { path: "demand", element: <DemandList /> },
      { path: "demand/:orderId", element: <Keyed param="orderId">{(k) => <DemandPage key={k} />}</Keyed> },
      { path: "work-orders", element: <WorkOrderList /> },
      { path: "work-orders/kitting", element: <KittingCheckPage /> },
      { path: "work-orders/:woId", element: <Keyed param="woId">{(k) => <WorkOrderPage key={k} />}</Keyed> },
      { path: "mrp", element: <MrpRunsPage /> },
      {
        path: "mrp/runs/:runId",
        element: <RunShell />,
        children: [
          { index: true, element: <RunSummaryTab /> },
          { path: "items", element: <RunItemsTab /> },
          { path: "items/:itemId", element: <ItemPlanPage /> },
          { path: "planned", element: <PlannedOrdersTab /> },
          { path: "exceptions", element: <ExceptionsTab /> },
          { path: "demand", element: <DemandProjectionTab /> },
          { path: "pegging", element: <PeggingPage /> },
          { path: "compare", element: <CompareView /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      { path: "shortages", element: <ShortagesPage /> },
      { path: "settings/members", element: <MembersPage /> },
      // ---------------------------------------------------------------- M3 (12)
      { path: "schedule", element: <ApsRunsPage /> },
      {
        path: "schedule/runs/:runId",
        element: <Keyed param="runId">{(k) => <ApsRunShell key={k} />}</Keyed>,
        children: [
          { index: true, element: <ApsSummaryTab /> },
          { path: "gantt", element: <ApsGanttTab /> },
          { path: "load", element: <ApsLoadTab /> },
          { path: "dispatch", element: <ApsDispatchTab /> },
          { path: "orders", element: <ApsOrdersTab /> },
          { path: "demand", element: <ApsDemandTab /> },
          { path: "overtime", element: <ApsOvertimeTab /> },
          { path: "exceptions", element: <ApsExceptionsTab /> },
          { path: "compare", element: <ApsCompareTab /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      // ---------------------------------------------------------------- M4 (12)
      { path: "floor/overview", element: <FloorOverview /> },
      { path: "floor/events", element: <FloorEvents /> },
      { path: "replan", element: <ReplanPage /> },
      { path: "kpis", element: <KpiPage /> },
      { path: "serials", element: <SerialsPage /> },
      { path: "serials/:serialId", element: <Keyed param="serialId">{(k) => <SerialPage key={k} />}</Keyed> },
      { path: "schedule/simulations", element: <SimulationsPage /> },
      { path: "schedule/simulations/:simulationId", element: <Keyed param="simulationId">{(k) => <SimulationPage key={k} />}</Keyed> },
      { path: "print/traveller/:woId", element: <TravellerPage /> },
      { path: "print/labels", element: <LabelsPage /> },
      // ---------------------------------------------------------------- M5
      {
        path: "integration",
        element: <IntegrationLayout />,
        children: [
          { index: true, element: <IntegrationOverview /> },
          { path: "settings", element: <IntegrationSettingsTab /> },
          { path: "endpoints", element: <EndpointsTab /> },
          { path: "deliveries", element: <DeliveriesTab /> },
          { path: "batches", element: <BatchesTab /> },
          { path: "batches/:batchId", element: <BatchPage /> },
          { path: "events", element: <EventsTab /> },
          { path: "filedrop", element: <FiledropTab /> },
          { path: "value-maps", element: <ValueMapsTab /> },
          { path: "reconciliation", element: <ReconciliationTab /> },
          { path: "reconciliation/:reconId", element: <ReconciliationPage /> },
          { path: "tokens", element: <PlantTokensTab /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      { path: "trace", element: <TracePage /> },
      { path: "trace/where-used", element: <WhereUsedPage /> },
      { path: "recalls", element: <RecallsPage /> },
      { path: "recalls/:recallId", element: <Keyed param="recallId">{(k) => <RecallPage key={k} />}</Keyed> },
      { path: "eco", element: <EcoListPage /> },
      { path: "eco/:ecoId", element: <Keyed param="ecoId">{(k) => <EcoPage key={k} />}</Keyed> },
      { path: "transfers", element: <TransfersPage /> },
      { path: "transfers/:transferId", element: <Keyed param="transferId">{(k) => <TransferPage key={k} />}</Keyed> },
      { path: "audit", element: <AuditPage /> },
      // ---------------------------------------------------------------- M6
      { path: "dashboard", element: <DashboardPage /> },
      // ---------------------------------------------------------------- M7 quality and Part 11
      { path: "esig/policies", element: <PoliciesPage /> },
      { path: "part11", element: <Part11Page /> },
      { path: "part11/exports", element: <Part11ExportsPage /> },
      { path: "qa/inspection-lots", element: <InspectionLotsPage /> },
      { path: "qa/inspection-lots/:lotId", element: <Keyed param="lotId">{(k) => <InspectionLotPage key={k} />}</Keyed> },
      { path: "qa/holds", element: <HoldsPage /> },
      { path: "qa/plans", element: <PlansPage /> },
      { path: "qa/plans/:planId", element: <Keyed param="planId">{(k) => <PlanPage key={k} />}</Keyed> },
      { path: "qa/schemes", element: <SchemesPage /> },
      { path: "qa/schemes/:schemeId", element: <Keyed param="schemeId">{(k) => <SchemePage key={k} />}</Keyed> },
      { path: "qa/settings", element: <QaSettingsPage /> },
      { path: "qa/ncrs", element: <NcrsPage /> },
      { path: "qa/ncrs/:ncrId", element: <Keyed param="ncrId">{(k) => <NcrPage key={k} />}</Keyed> },
      { path: "qa/capas", element: <CapasPage /> },
      { path: "qa/capas/:capaId", element: <Keyed param="capaId">{(k) => <CapaPage key={k} />}</Keyed> },
      { path: "qa/complaints", element: <ComplaintsPage /> },
      { path: "qa/complaints/:complaintId", element: <Keyed param="complaintId">{(k) => <ComplaintPage key={k} />}</Keyed> },
      { path: "qa/field-actions", element: <FieldActionsPage /> },
      { path: "qa/field-actions/:faId", element: <Keyed param="faId">{(k) => <FieldActionPage key={k} />}</Keyed> },
      { path: "qa/equipment", element: <EquipmentListPage /> },
      { path: "qa/equipment/:equipmentId", element: <Keyed param="equipmentId">{(k) => <EquipmentPage key={k} />}</Keyed> },
      { path: "print/qa/:type/:id", element: <PrintRecordPage /> },
      // ---------------------------------------------------------------- M8 planning at volume
      { path: "forecast", element: <ForecastPage /> },
      { path: "forecast/accuracy", element: <AccuracyPage /> },
      { path: "invopt", element: <InvoptPage /> },
      { path: "kanban", element: <KanbanPage /> },
      { path: "rate", element: <RateRunsPage /> },
      { path: "sterilisation", element: <SterilisationPage /> },
      { path: "validation", element: <ValidationPage /> },
      { path: "rate/runs/:runId/:tab?", element: <Keyed param="runId">{(k) => <RateRunPage key={k} />}</Keyed> },
      { path: "print/kanban/:loopId", element: <KanbanCardsPrint /> },
      // ---------------------------------------------------------------- M9 network, S&OP, trade
      { path: "network", element: <NetworkHome /> },
      { path: "network/sourcing", element: <SourcingPage /> },
      { path: "network/runs/:runId/:tab?", element: <Keyed param="runId">{(k) => <NetRunPage key={k} />}</Keyed> },
      { path: "sop", element: <SopCyclesPage /> },
      { path: "sop/scenarios/:scenarioId", element: <Keyed param="scenarioId">{(k) => <ScenarioPage key={k} />}</Keyed> },
      { path: "mps", element: <MpsPage /> },
      { path: "trade/reports/:reportId", element: <Keyed param="reportId">{(k) => <TradeReportPage key={k} />}</Keyed> },
      { path: "trade/:tab?", element: <TradePage /> },
      { path: "sourcing-risk", element: <SourcingRiskPage /> },
      { path: "sop/cycles/:cycleId/:step?", element: <Keyed param="cycleId">{(k) => <SopCyclePage key={k} />}</Keyed> },
      { path: "*", element: <MfgNotFound /> },
    ],
  },
];
