import { ThinkingOrb, type OrbState } from "thinking-orbs";
import { ORB_LABELS } from "../model/orbState";
import { cn } from "../../../lib/utils";
import React from 'react';
interface AgentOrbProps {
    state: OrbState;
    size?: 20 | 64;
    paused?: boolean;
    className?: string;
    label?: string;
}
export const AgentOrb: React.FC<AgentOrbProps> = ({ state, size = 20, paused, className, label }) => (<ThinkingOrb state={state} size={size} theme="light" paused={paused} aria-label={label ?? ORB_LABELS[state]} className={cn('agent-orb shrink-0', className)}/>);
