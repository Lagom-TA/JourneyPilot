export type GenerationWorkspaceScene = 'home' | 'plan' | 'plan-live' | 'plan-failed' | 'plan-empty' | 'questions' | 'question-next' | 'location-retry' | 'research-retry' | 'research' | 'empty' | 'long' | 'assumed' | 'pending' | 'route' | 'redo' | 'delivery' | 'completed' | 'partial' | 'failed' | 'cancelled' | 'stopping' | 'interrupted' | 'unrecoverable' | 'readonly' | 'recovery-loading' | 'recovery-error';

type GenerationFixtureAction =
  | { type: 'ADD_THINKING_STEP'; payload: { id: string; agentName: string; content: string; progressStatus: 'running' | 'completed' | 'failed'; stepName: string; timestamp: Date } }
  | { type: 'SET_UNDERSTANDING_QUESTIONS'; payload: { runId: string; revision: number; approvalToken: string; questions: never[]; retryLocation: boolean; retryResearch: boolean } };

declare global {
  interface Window {
    __generationWorkspace?: { setScene: (scene: GenerationWorkspaceScene) => void; dispatch: (action: GenerationFixtureAction) => void };
  }
}
