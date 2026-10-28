import { AnimatePresence, useReducedMotion, type Variants } from 'motion/react';
import { ArrowRight } from 'lucide-react';
import React from 'react';
import { PresenceSection } from '../../../../components/ui/PresenceSurface';
import { SegmentedTabs, type SegmentedTab } from '../../../../components/ui/SegmentedTabs';
import { duration, easing } from '../../../../lib/motion';
import { ATLAS_SCENES, AtlasSceneArtwork, type AtlasScene, type AtlasSceneId } from './TravelAtlasScenes';

const ATLAS_ROTATION_MS = 6500;

interface AtlasTransition {
  direction: number;
  reduced: boolean;
}

const sceneVariants: Variants = {
  enter: ({ direction, reduced }: AtlasTransition) => ({
    opacity: 0,
    x: reduced ? 0 : direction * 30,
    scale: reduced ? 1 : 1.025,
    clipPath: reduced
      ? 'inset(0 0% 0 0%)'
      : direction > 0
        ? 'inset(0 0% 0 18%)'
        : 'inset(0 18% 0 0%)',
  }),
  center: ({ reduced }: AtlasTransition) => ({
    opacity: 1,
    x: 0,
    scale: 1,
    clipPath: 'inset(0 0% 0 0%)',
    transition: { duration: reduced ? 0 : duration.emphasis, ease: easing.decelerate },
  }),
  exit: ({ direction, reduced }: AtlasTransition) => ({
    opacity: 0,
    x: reduced ? 0 : direction * -18,
    scale: reduced ? 1 : 0.99,
    transition: { duration: reduced ? 0 : duration.slow, ease: easing.accelerate },
  }),
};

function setPointerPosition(node: HTMLElement, x: number, y: number) {
  node.style.setProperty('--atlas-far-x', `${x * -10}px`);
  node.style.setProperty('--atlas-far-y', `${y * -8}px`);
  node.style.setProperty('--atlas-near-x', `${x * 12}px`);
  node.style.setProperty('--atlas-near-y', `${y * 10}px`);
  node.style.setProperty('--atlas-card-x', `${x * 5}px`);
  node.style.setProperty('--atlas-card-y', `${y * 4}px`);
  node.style.setProperty('--atlas-tilt-x', `${y * -2.2}deg`);
  node.style.setProperty('--atlas-tilt-y', `${x * 2.8}deg`);
  node.style.setProperty('--atlas-light-x', `${50 + x * 100}%`);
  node.style.setProperty('--atlas-light-y', `${50 + y * 100}%`);
}

export const TravelAtlas: React.FC<{
  onUseExample: (scene: AtlasScene) => void;
}> = ({ onUseExample }) => {
  const reducedMotion = useReducedMotion();
  const atlasRef = React.useRef<HTMLElement>(null);
  const pointerFrame = React.useRef<number | null>(null);
  const tabsId = React.useId();
  const [current, setCurrent] = React.useState({ index: 0, direction: 1 });
  const scene = ATLAS_SCENES[current.index]!;
  const transition: AtlasTransition = { direction: current.direction, reduced: Boolean(reducedMotion) };

  const tabs = React.useMemo<ReadonlyArray<SegmentedTab<AtlasSceneId>>>(() => ATLAS_SCENES.map((item) => ({
    id: item.id,
    label: item.tab,
    testId: `atlas-tab-${item.id}`,
    domId: `${tabsId}-${item.id}-tab`,
    panelId: `${tabsId}-panel`,
  })), [tabsId]);

  const resetPointer = React.useCallback(() => {
    if (pointerFrame.current !== null) {
      window.cancelAnimationFrame(pointerFrame.current);
      pointerFrame.current = null;
    }
    if (atlasRef.current) setPointerPosition(atlasRef.current, 0, 0);
  }, []);

  React.useEffect(() => () => {
    if (pointerFrame.current !== null) window.cancelAnimationFrame(pointerFrame.current);
  }, []);

  React.useEffect(() => {
    if (reducedMotion) resetPointer();
  }, [reducedMotion, resetPointer]);

  React.useEffect(() => {
    const node = atlasRef.current;
    if (!node) return;
    let frame: number | null = null;
    const startedAt = performance.now();
    node.style.setProperty('--atlas-progress', '0');
    node.style.setProperty('--atlas-frost', '4px');
    const updateProgress = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / ATLAS_ROTATION_MS);
      node.style.setProperty('--atlas-progress', progress.toFixed(4));
      node.style.setProperty('--atlas-frost', `${4 + progress * 14}px`);
      if (progress < 1) frame = window.requestAnimationFrame(updateProgress);
    };
    frame = window.requestAnimationFrame(updateProgress);
    const timer = window.setTimeout(() => {
      setCurrent((previous) => ({
        index: (previous.index + 1) % ATLAS_SCENES.length,
        direction: 1,
      }));
    }, ATLAS_ROTATION_MS);
    return () => {
      window.clearTimeout(timer);
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, [current.index]);

  const selectScene = (id: AtlasSceneId) => {
    const nextIndex = ATLAS_SCENES.findIndex((item) => item.id === id);
    if (nextIndex < 0) return;
    resetPointer();
    setCurrent((previous) => previous.index === nextIndex
      ? previous
      : { index: nextIndex, direction: nextIndex > previous.index ? 1 : -1 });
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLElement>) => {
    if (reducedMotion || event.pointerType !== 'mouse' || pointerFrame.current !== null) return;
    const { clientX, clientY } = event;
    pointerFrame.current = window.requestAnimationFrame(() => {
      pointerFrame.current = null;
      const node = atlasRef.current;
      if (!node) return;
      const bounds = node.getBoundingClientRect();
      const x = Math.max(-0.5, Math.min(0.5, (clientX - bounds.left) / bounds.width - 0.5));
      const y = Math.max(-0.5, Math.min(0.5, (clientY - bounds.top) / bounds.height - 0.5));
      setPointerPosition(node, x, y);
    });
  };

  return (
    <aside
      ref={atlasRef}
      className="travel-atlas"
      aria-label={`${scene.cardTitle}旅行灵感示例`}
      data-scene={scene.id}
      data-testid="travel-atlas"
      onPointerMove={handlePointerMove}
      onPointerLeave={resetPointer}
    >
      <SegmentedTabs
        aria-label="选择旅行灵感示例"
        tabs={tabs}
        value={scene.id}
        onChange={selectScene}
        className="atlas-scene-tabs"
      />

      <div
        className="atlas-panel"
        role="tabpanel"
        id={`${tabsId}-panel`}
        aria-labelledby={`${tabsId}-${scene.id}-tab`}
      >
        <AnimatePresence initial={false} custom={transition}>
          <PresenceSection
            key={scene.id}
            className={`atlas-scene atlas-theme-${scene.id}`}
            custom={transition}
            variants={sceneVariants}
            initial="enter"
            animate="center"
            exit="exit"
          >
            <AtlasSceneArtwork scene={scene.id} />
            <div className="atlas-lens-position atlas-parallax-near" aria-hidden="true">
              <div className="atlas-liquid-lens" />
            </div>
            <div className="atlas-pointer-light" aria-hidden="true" />

            <div className="atlas-card-position">
              <button
                type="button"
                className="atlas-example-card"
                aria-label={`用这个灵感填入规划：${scene.cardTitle}`}
                data-testid="atlas-use-example"
                onClick={() => onUseExample(scene)}
              >
                <span className="atlas-example-top">{scene.subtitle}</span>
                <span className="atlas-example-title">{scene.cardTitle}</span>
                <span className="atlas-example-description">{scene.description}</span>
                <span className="atlas-example-facts">
                  <span><small>出发</small><strong>{scene.origin.name}</strong></span>
                  <span><small>同行</small><strong>{scene.adults} 位成人</strong></span>
                  <span><small>预算</small><strong>约 ¥{scene.budgetCny.toLocaleString('zh-CN')}</strong></span>
                </span>
                <span className="atlas-example-action">
                  填入规划信息
                  <ArrowRight size={15} aria-hidden="true" />
                </span>
              </button>
            </div>
          </PresenceSection>
        </AnimatePresence>
      </div>
    </aside>
  );
};
