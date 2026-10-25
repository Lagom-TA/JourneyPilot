import { LazyMotion } from "motion/react";
import React from 'react';
const loadDomMax = () => import('../../lib/motion-features').then((mod) => mod.default);
export const CanvasMotion: React.FC<{
    children: React.ReactNode;
}> = ({ children }) => (<LazyMotion features={loadDomMax}>{children}</LazyMotion>);
