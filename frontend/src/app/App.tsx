import { AnimatePresence } from "motion/react";
import { AppProvider } from "./state/AppProvider";
import { useApp } from "./state/AppContext";
import { MotionProviders } from "./motion/MotionProviders";
import { MainLayout } from "./layout/MainLayout";
import { TripWorkspaceShell } from "./layout/TripWorkspaceShell";
import { PageSkeleton } from "./components/PageSkeleton";
import { LazyViewBoundary } from "../components/ui/LazyViewBoundary";
import { PresenceFrame } from "../components/ui/PresenceSurface";
import { useSessionManager } from "./session/useSessionManager";
import { ViewUrlSync } from "./navigation/ViewUrlSync";
import { DeliveryEventRecovery } from "./session/useDeliveryEventRecovery";
import { resolveViewTransition, viewTransitionVariants } from "./navigation/viewTransition";
import React, { Suspense, lazy } from 'react';
const KnowledgeBasePage = lazy(() => import('../features/knowledge/pages/KnowledgeBasePage').then((m) => ({ default: m.KnowledgeBasePage })));
const MyTripsPage = lazy(() => import('../features/travel/pages/MyTripsPage').then((m) => ({ default: m.MyTripsPage })));
const PresetLibraryPage = lazy(() => import('../features/presets/pages/PresetLibraryPage').then((m) => ({ default: m.PresetLibraryPage })));
const UserPreferencesPage = lazy(() => import('../features/settings/pages/UserPreferencesPage').then((m) => ({ default: m.UserPreferencesPage })));
const ViewContent: React.FC<{
    view: string;
}> = ({ view }) => {
    switch (view) {
        case 'chat':
            return <TripWorkspaceShell />;
        case 'trips':
            return <MyTripsPage />;
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
    const previousRef = React.useRef({ view, conversationEpoch: state.conversationEpoch });
    const previous = previousRef.current;
    const transition = resolveViewTransition(
        previous.view,
        view,
        previous.conversationEpoch !== state.conversationEpoch && view === 'chat',
    );
    React.useLayoutEffect(() => {
        previousRef.current = { view, conversationEpoch: state.conversationEpoch };
    }, [state.conversationEpoch, view]);
    return (<AnimatePresence mode="popLayout" initial={false} custom={transition}>
      <PresenceFrame key={view} className="h-full min-h-0 w-full bg-bg" custom={transition} variants={viewTransitionVariants} initial="enter" animate="center" exit="exit">
        <LazyViewBoundary resetKey={boundaryResetKey}>
          <Suspense fallback={<PageSkeleton />}>
            <ViewContent view={view}/>
          </Suspense>
        </LazyViewBoundary>
      </PresenceFrame>
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
