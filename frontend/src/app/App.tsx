import { AnimatePresence, m } from "motion/react";
import { AppProvider } from "./state/AppProvider";
import { useApp } from "./state/AppContext";
import { MotionProviders } from "./motion/MotionProviders";
import { MainLayout } from "./layout/MainLayout";
import { TripWorkspaceShell } from "./layout/TripWorkspaceShell";
import { PageSkeleton } from "./components/PageSkeleton";
import { LazyViewBoundary } from "../components/ui/LazyViewBoundary";
import { useSessionManager } from "./session/useSessionManager";
import { ViewUrlSync } from "./navigation/ViewUrlSync";
import { DeliveryEventRecovery } from "./session/useDeliveryEventRecovery";
import { duration, easing } from "../lib/motion";
import React, { Suspense, lazy } from 'react';
const KnowledgeBasePage = lazy(() => import('../features/knowledge/pages/KnowledgeBasePage').then((m) => ({ default: m.KnowledgeBasePage })));
const PresetLibraryPage = lazy(() => import('../features/presets/pages/PresetLibraryPage').then((m) => ({ default: m.PresetLibraryPage })));
const UserPreferencesPage = lazy(() => import('../features/settings/pages/UserPreferencesPage').then((m) => ({ default: m.UserPreferencesPage })));
const ViewContent: React.FC<{
    view: string;
}> = ({ view }) => {
    switch (view) {
        case 'chat':
            return <TripWorkspaceShell />;
        case 'knowledge-base':
            return <KnowledgeBasePage />;
        case 'presets':
            return <PresetLibraryPage />;
        case 'user-preferences':
            return <UserPreferencesPage />;
        default:
            return <TripWorkspaceShell />;
    }
};
const ViewRouter: React.FC = () => {
    const { state } = useApp();
    const view = state.activeView;
    const boundaryResetKey = view === 'chat' ? `${view}:${state.conversationEpoch}` : view;
    return (<AnimatePresence mode="wait" initial={false}>
      <m.div key={view} className="h-full min-h-0" initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { duration: duration.base, ease: easing.decelerate } }} exit={{ opacity: 0, transition: { duration: duration.fast, ease: easing.accelerate } }}>
        <LazyViewBoundary resetKey={boundaryResetKey}>
          <Suspense fallback={<PageSkeleton />}>
            <ViewContent view={view}/>
          </Suspense>
        </LazyViewBoundary>
      </m.div>
    </AnimatePresence>);
};
const App: React.FC = () => {
    return (<AppProvider>
      <MotionProviders>
        <SessionBootstrap />
        <DeliveryEventRecovery />
        <ViewUrlSync />
        <MainLayout>
          <ViewRouter />
        </MainLayout>
      </MotionProviders>
    </AppProvider>);
};
const SessionBootstrap: React.FC = () => {
    const { initializeSessions } = useSessionManager();
    React.useEffect(() => {
        void initializeSessions();
    }, [initializeSessions]);
    return null;
};
export default App;
