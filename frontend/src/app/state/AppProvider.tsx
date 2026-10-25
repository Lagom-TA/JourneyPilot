import { useReducer } from "react";
import { appReducer } from "./appReducer";
import { initialState } from "./initialState";
import { type ActiveStreamHandle, type SessionRuntimeSnapshot } from "../session/runtimeSnapshot";
import { type AppState } from "./state";
import { AppContext } from "./AppContext";
import React, { type ReactNode } from 'react';
export const AppProvider: React.FC<{
    children: ReactNode;
}> = ({ children }) => {
    const [state, dispatch] = useReducer(appReducer, initialState);
    const activeStreamAbortRef = React.useRef<AbortController | null>(null);
    const activeStreamRef = React.useRef<ActiveStreamHandle | null>(null);
    const currentStateRef = React.useRef<AppState>(state);
    const sessionRuntimeCacheRef = React.useRef<Map<string, SessionRuntimeSnapshot>>(new Map());
    React.useEffect(() => {
        currentStateRef.current = state;
    }, [state]);
    React.useEffect(() => {
        const handleResize = () => {
            if (window.innerWidth < 1024) {
                dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: true });
            }
        };
        handleResize();
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);
    const value = React.useMemo(() => ({
        state,
        dispatch,
        activeStreamAbortRef,
        activeStreamRef,
        currentStateRef,
        sessionRuntimeCacheRef,
    }), [state]);
    return (<AppContext.Provider value={value}>
      {children}
    </AppContext.Provider>);
};
