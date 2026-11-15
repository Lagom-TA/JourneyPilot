import { AnimatePresence, m, type Variants } from 'motion/react';
import { ArrowRight, UsersRound } from 'lucide-react';
import React from 'react';
import islandArtwork from '../../../../assets/home/island.webp';
import jiangnanArtwork from '../../../../assets/home/jiangnan.webp';
import northwestArtwork from '../../../../assets/home/northwest.webp';
import southwestArtwork from '../../../../assets/home/southwest.webp';
import ticketPaper from '../../../../assets/paper/ticket-main.webp';
import luggagePaper from '../../../../assets/paper/tag-luggage.webp';
import luggageWidePaper from '../../../../assets/paper/tag-luggage-wide.webp';
import islandPrint from '../../../../assets/paper/print-island.webp';
import jiangnanPrint from '../../../../assets/paper/print-jiangnan.webp';
import northwestPrint from '../../../../assets/paper/print-northwest.webp';
import southwestPrint from '../../../../assets/paper/print-southwest.webp';
import { SegmentedTabs, type SegmentedTab } from '../../../../components/ui/SegmentedTabs';
import { useMediaQuery } from '../../../../hooks/useMediaQuery';
import { duration, easing } from '../../../../lib/motion';
import { ATLAS_SCENES, type AtlasScene, type AtlasSceneId } from './TravelAtlasScenes';

const ROTATION_MS = 6_500;
const ARTWORK: Record<AtlasSceneId, string> = { island: islandArtwork, jiangnan: jiangnanArtwork, northwest: northwestArtwork, southwest: southwestArtwork };
const PRINT: Record<AtlasSceneId, string> = { island: islandPrint, jiangnan: jiangnanPrint, northwest: northwestPrint, southwest: southwestPrint };
const decodedImages = new Map<string, Promise<void>>();
type SceneDirection = -1 | 1;

const landscapeMotion: Variants = {
  enter: (direction: SceneDirection) => ({ opacity: 0, x: `${direction * 2}%`, scale: 1.06 }),
  center: { opacity: 1, x: '0%', scale: 1.06 },
  exit: (direction: SceneDirection) => ({ opacity: 1, x: `${direction * -0.5}%`, scale: 1.06 }),
};

const paperMotion: Variants = {
  enter: (direction: SceneDirection) => ({ opacity: 0, x: direction * 20 }),
  center: { opacity: 1, x: 0 },
};

function decodeImage(src: string): Promise<void> {
  const cached = decodedImages.get(src);
  if (cached) return cached;
  const image = new Image();
  image.src = src;
  const decoded = image.decode().catch((error: unknown) => {
    decodedImages.delete(src);
    throw error;
  });
  decodedImages.set(src, decoded);
  return decoded;
}

export const TravelAtlas: React.FC<{ onUseExample: (scene: AtlasScene) => void }> = ({ onUseExample }) => {
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const tabsId = React.useId();
  const [{ sceneId, direction, revision }, setScene] = React.useState<{ sceneId: AtlasSceneId; direction: SceneDirection; revision: number }>({ sceneId: 'northwest', direction: 1, revision: 0 });
  const [hovered, setHovered] = React.useState(false);
  const [focused, setFocused] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [hidden, setHidden] = React.useState(false);
  const [changing, setChanging] = React.useState(false);
  const [rotationAttempt, setRotationAttempt] = React.useState(0);
  const rotationAttemptRef = React.useRef(0);
  const mounted = React.useRef(true);
  const switchSequence = React.useRef(0);
  const progressRef = React.useRef<HTMLSpanElement>(null);
  const elapsed = React.useRef({ sceneId, ms: 0 });
  const tablistRef = React.useRef<HTMLDivElement>(null);
  const scene = ATLAS_SCENES.find((item) => item.id === sceneId)!;
  const sceneIndex = ATLAS_SCENES.indexOf(scene);
  const nextScene = ATLAS_SCENES[(sceneIndex + 1) % ATLAS_SCENES.length]!;
  const interactionPaused = Boolean(reducedMotion || hovered || focused || editing || hidden);
  const pauseRef = React.useRef(interactionPaused);
  pauseRef.current = interactionPaused;
  const paused = interactionPaused || changing;

  React.useLayoutEffect(() => {
    elapsed.current = { sceneId, ms: 0 };
  }, [sceneId]);

  React.useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; switchSequence.current += 1; };
  }, []);

  React.useEffect(() => {
    const updateEditing = () => {
      const active = document.activeElement;
      setEditing(active instanceof Element && Boolean(active.closest('.planner-card, [role="dialog"]')));
    };
    const afterFocus = () => queueMicrotask(updateEditing);
    const updateVisibility = () => setHidden(document.hidden);
    updateEditing();
    updateVisibility();
    document.addEventListener('focusin', updateEditing);
    document.addEventListener('focusout', afterFocus);
    document.addEventListener('visibilitychange', updateVisibility);
    return () => {
      document.removeEventListener('focusin', updateEditing);
      document.removeEventListener('focusout', afterFocus);
      document.removeEventListener('visibilitychange', updateVisibility);
    };
  }, []);

  const selectScene = React.useCallback((id: AtlasSceneId, automatic = false, requestedDirection?: SceneDirection) => {
    const sequence = ++switchSequence.current;
    if (id === sceneId) { setChanging(false); return; }
    const targetIndex = ATLAS_SCENES.findIndex((item) => item.id === id);
    const nextDirection = requestedDirection ?? (targetIndex > sceneIndex ? 1 : -1);
    setChanging(true);
    void Promise.all([decodeImage(ARTWORK[id]), decodeImage(PRINT[id])]).then(() => {
      if (!mounted.current || switchSequence.current !== sequence) return;
      if (automatic && pauseRef.current) { setChanging(false); return; }
      setScene((previous) => ({ sceneId: id, direction: nextDirection, revision: previous.revision + 1 }));
      setChanging(false);
    }).catch(() => {
      // 素材未就绪时整组保留，避免纸面与风景显示不同主题。
      if (mounted.current && switchSequence.current === sequence) {
        elapsed.current.ms = 0;
        rotationAttemptRef.current += 1;
        setRotationAttempt(rotationAttemptRef.current);
        const active = document.activeElement;
        if (active instanceof HTMLElement && active.id === `${tabsId}-${id}-tab` && tablistRef.current?.contains(active)) {
          document.getElementById(`${tabsId}-${sceneId}-tab`)?.focus();
        }
        setChanging(false);
      }
    });
  }, [sceneId, sceneIndex, tabsId]);

  React.useEffect(() => {
    const preload = window.setTimeout(() => {
      const previous = ATLAS_SCENES[(sceneIndex - 1 + ATLAS_SCENES.length) % ATLAS_SCENES.length]!;
      for (const item of [nextScene, previous]) {
        void Promise.all([decodeImage(ARTWORK[item.id]), decodeImage(PRINT[item.id])]).catch(() => {});
      }
    }, 1200);
    return () => window.clearTimeout(preload);
  }, [sceneIndex, nextScene]);

  React.useEffect(() => {
    const indicator = progressRef.current;
    if (!indicator) return;
    const initialElapsed = elapsed.current.ms;
    indicator.style.transform = `scaleX(${initialElapsed / ROTATION_MS})`;
    if (paused) return;
    const attempt = rotationAttempt;

    const animation = indicator.animate(
      [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }],
      { duration: ROTATION_MS, easing: 'linear', fill: 'both' },
    );
    animation.currentTime = initialElapsed;
    const timer = window.setTimeout(() => {
      elapsed.current.ms = ROTATION_MS;
      selectScene(nextScene.id, true, 1);
    }, ROTATION_MS - initialElapsed);
    return () => {
      window.clearTimeout(timer);
      if (elapsed.current.sceneId === sceneId && rotationAttemptRef.current === attempt) {
        elapsed.current.ms = Math.min(ROTATION_MS, Number(animation.currentTime) || 0);
      }
      indicator.style.transform = `scaleX(${elapsed.current.ms / ROTATION_MS})`;
      animation.cancel();
    };
  }, [sceneId, nextScene.id, paused, rotationAttempt, selectScene]);

  const tabs: ReadonlyArray<SegmentedTab<AtlasSceneId>> = ATLAS_SCENES.map((item) => ({
    id: item.id,
    label: <>{item.id === sceneId && <span ref={progressRef} className="atlas-tab-progress" aria-hidden="true" data-testid="atlas-progress" />}<span className="atlas-tab-label">{item.tab}</span></>,
    testId: `atlas-tab-${item.id}`, domId: `${tabsId}-${item.id}-tab`, panelId: `${tabsId}-panel`,
  }));
  const sparkles = <span className="atlas-paper-sparks" aria-hidden="true"><i /><i /><i /></span>;

  return (
    <>
      <div className="home-landscape" aria-hidden="true" data-theme={sceneId}>
        <AnimatePresence initial={false} custom={direction}>
          <m.div key={revision} className="atlas-scene" custom={direction} variants={landscapeMotion} initial="enter" animate="center" exit="exit" transition={{ duration: reducedMotion ? 0 : duration.detail, ease: easing.standard }}>
            {/* React 18 运行时不识别 camelCase 的 fetchPriority（19 才支持），浏览器读取的是小写属性；按 React 的提示用小写注入。 */}
            <img className="atlas-artwork" src={ARTWORK[sceneId]} alt="" decoding="async" {...({ fetchpriority: 'high' } as React.ImgHTMLAttributes<HTMLImageElement>)} />
          </m.div>
        </AnimatePresence>
      </div>
      <aside className="travel-atlas" aria-label="旅行灵感" aria-busy={changing || undefined} data-scene={sceneId} data-direction={direction === 1 ? 'forward' : 'backward'} data-autoplay={paused ? 'paused' : 'running'} data-testid="travel-atlas"
        onPointerEnter={(event) => { if (event.pointerType === 'mouse') setHovered(true); }}
        onPointerLeave={(event) => { if (event.pointerType === 'mouse') setHovered(false); }} onFocusCapture={() => setFocused(true)}
        onBlurCapture={(event) => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
        <div ref={tablistRef} className="atlas-toolbar">
          <SegmentedTabs aria-label="选择旅行灵感示例" tabs={tabs} value={sceneId} onChange={(id, tabDirection) => selectScene(id, false, tabDirection)} className="atlas-scene-tabs" />
        </div>
        <div className="atlas-examples" role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${sceneId}-tab`}>
          <m.div key={sceneId} className="atlas-paper-group" custom={direction} variants={paperMotion} initial={reducedMotion ? false : 'enter'} animate="center" transition={{ duration: reducedMotion ? 0 : duration.slow, ease: easing.decelerate }}>
            <button type="button" disabled={changing} className="atlas-example-card is-primary" aria-label={`采用旅行提案：${scene.cardTitle}`} data-theme={sceneId} data-testid="atlas-use-example" onClick={() => onUseExample(scene)}>
              <img className="atlas-paper" src={ticketPaper} alt="" aria-hidden="true" draggable={false} />
              <span className="atlas-example-body">
                <span className="atlas-example-origin">{scene.origin.name}出发</span>
                <span className="atlas-example-title">{scene.destinations.map((place, index) => <React.Fragment key={place.place_id}>{index > 0 && <ArrowRight size={16} aria-hidden="true" />}<span>{place.name}</span></React.Fragment>)}</span>
                <span className="atlas-invitation">{scene.invitation}</span>
                <span className="atlas-trip-details"><span><UsersRound size={12} aria-hidden="true" />{scene.adults} 人</span><span>预算 ¥{scene.budgetCny.toLocaleString('zh-CN')}</span></span>
              </span>
              <span className="atlas-ticket-stub"><span className="atlas-day-number">{scene.days}</span><span className="atlas-day-unit">天</span><ArrowRight className="atlas-ticket-arrow" size={18} aria-hidden="true" /></span>
              {sparkles}
            </button>
            <button type="button" disabled={changing} className="atlas-example-card is-secondary" aria-label={`采用旅行时刻：${scene.moment.join('，')}`} data-theme={sceneId} data-testid="atlas-use-alternate" onClick={() => onUseExample(scene)}>
              <picture className="atlas-paper-frame" aria-hidden="true"><source media="(width < 640px)" srcSet={luggageWidePaper} /><img className="atlas-paper" src={luggagePaper} alt="" draggable={false} /></picture>
              <span className="atlas-tag-body">
                <img className="atlas-place-print" src={PRINT[sceneId]} alt="" aria-hidden="true" draggable={false} />
                <span className="atlas-tag-moment">{scene.moment[0]}<br />{scene.moment[1]}</span>
                <span className="atlas-highlights">{scene.highlights.map((item) => <span key={item}>{item}</span>)}</span>
              </span>
              {sparkles}
            </button>
          </m.div>
        </div>
      </aside>
    </>
  );
};
