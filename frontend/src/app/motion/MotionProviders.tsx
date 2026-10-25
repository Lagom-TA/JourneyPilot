import { LazyMotion, MotionConfig, domAnimation } from "motion/react";
import React from 'react';
export const MotionProviders: React.FC<{
    children: React.ReactNode;
}> = ({ children }) => (<MotionConfig reducedMotion="user">
    <LazyMotion features={domAnimation} strict>
      {children}
    </LazyMotion>
  </MotionConfig>);
