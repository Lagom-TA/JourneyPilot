import { AnimatePresence, m, useMotionValue, useReducedMotion, useTransform } from 'motion/react';
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
import { duration, easing } from '../../../../lib/motion';
import { ATLAS_SCENES, type AtlasScene, type AtlasSceneId } from './TravelAtlasScenes';

const ROTATION_MS = 14_000;
const ARTWORK: Record<AtlasSceneId, string> = { island: islandArtwork, jiangnan: jiangnanArtwork, northwest: northwestArtwork, southwest: southwestArtwork };
const PRINT: Record<AtlasSceneId, string> = { island: islandPrint, jiangnan: jiangnanPrint, northwest: northwestPrint, southwest: southwestPrint };
const decodedImages = new Map<string, Promise<void>>();

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
  const reducedMotion = useReducedMotion();
  const tabsId = React.useId();
  const [sceneId, setSceneId] = React.useState<AtlasSceneId>('northwest');
  const [hovered, setHovered] = React.useState(false);
  const [focused, setFocused] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [hidden, setHidden] = React.useState(false);
  const [changing, setChanging] = React.useState(false);
  const mounted = React.useRef(true);
  const switchSequence = React.useRef(0);
  const progress = useMotionValue(0);
  const progressMask = useTransform(progress, (value) => `inset(0 ${(1 - value) * 100}% 0 0)`);
  const frostBlur = useTransform(progress, (value) => `blur(${8 + value * 14}px)`);
  const elapsed = React.useRef({ sceneId, ms: 0 });
  const scene = ATLAS_SCENES.find((item) => item.id === sceneId)!;
  const nextScene = ATLAS_SCENES[(ATLAS_SCENES.indexOf(scene) + 1) % ATLAS_SCENES.length]!;
  const interactionPaused = Boolean(reducedMotion || hovered || focused || editing || hidden);
  const pauseRef = React.useRef(interactionPaused);
  pauseRef.current = interactionPaused;
  const paused = interactionPaused || changing;

  React.useLayoutEffect(() => {
    elapsed.current = { sceneId, ms: 0 };
    progress.set(0);
  }, [sceneId, progress]);

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

  const selectScene = React.useCallback((id: AtlasSceneId, automatic = false) => {
    const sequence = ++switchSequence.current;
    if (id === sceneId) { setChanging(false); return; }
    setChanging(true);
    void Promise.all([decodeImage(ARTWORK[id]), decodeImage(PRINT[id])]).then(() => {
      if (!mounted.current || switchSequence.current !== sequence) return;
      if (automatic && pauseRef.current) { setChanging(false); return; }
      setSceneId(id);
      setChanging(false);
    }).catch(() => {
      // 素材未就绪时整组保留，避免纸面与风景显示不同主题。
      if (mounted.current && switchSequence.current === sequence) {
        elapsed.current.ms = 0;
        progress.set(0);
        setChanging(false);
      }
    });
  }, [sceneId, progress]);

  React.useEffect(() => {
    if (paused) return;
    const started = performance.now();
    const initialElapsed = elapsed.current.ms;
    const advance = () => {
      if (elapsed.current.sceneId !== sceneId) return;
      elapsed.current.ms = Math.min(ROTATION_MS, initialElapsed + performance.now() - started);
      progress.set(elapsed.current.ms / ROTATION_MS);
    };
    let frame = 0;
    const paint = () => {
      advance();
      if (elapsed.current.ms < ROTATION_MS) frame = window.requestAnimationFrame(paint);
    };
    frame = window.requestAnimationFrame(paint);
    const timer = window.setTimeout(() => {
      elapsed.current.ms = ROTATION_MS;
      progress.set(1);
      selectScene(nextScene.id, true);
    }, ROTATION_MS - initialElapsed);
    const preload = window.setTimeout(() => {
      void Promise.all([decodeImage(ARTWORK[nextScene.id]), decodeImage(PRINT[nextScene.id])]).catch(() => {});
    }, 1200);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
      window.clearTimeout(preload);
      advance();
    };
  }, [sceneId, nextScene.id, paused, progress, selectScene]);

  const tabs: ReadonlyArray<SegmentedTab<AtlasSceneId>> = ATLAS_SCENES.map((item) => ({
    id: item.id,
    label: <><m.span className="atlas-tab-frost" aria-hidden="true" data-testid={item.id === sceneId ? 'atlas-progress' : undefined} style={{ clipPath: progressMask, backdropFilter: frostBlur, WebkitBackdropFilter: frostBlur }} /><span className="atlas-tab-label">{item.tab}</span></>,
    testId: `atlas-tab-${item.id}`, domId: `${tabsId}-${item.id}-tab`, panelId: `${tabsId}-panel`,
  }));
  const sparkles = <span className="atlas-paper-sparks" aria-hidden="true"><i /><i /><i /></span>;

  return (
    <>
      <div className="home-landscape" aria-hidden="true" data-theme={sceneId}>
        <AnimatePresence initial={false}>
          <m.div key={sceneId} className="atlas-scene" initial={{ clipPath: reducedMotion ? 'none' : 'inset(0 0 0 100%)' }} animate={{ clipPath: 'inset(0 0 0 0%)' }} exit={{ opacity: 0 }} transition={{ duration: reducedMotion ? 0 : duration.emphasis, ease: easing.decelerate }}>
            <img className="atlas-artwork" src={ARTWORK[sceneId]} alt="" decoding="async" fetchPriority="high" />
          </m.div>
        </AnimatePresence>
      </div>
      <aside className="travel-atlas" aria-label="旅行灵感" aria-busy={changing || undefined} data-scene={sceneId} data-autoplay={paused ? 'paused' : 'running'} data-testid="travel-atlas"
        onPointerOver={(event) => { if (event.pointerType === 'mouse') setHovered(true); }}
        onPointerOut={(event) => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setHovered(false); }} onFocusCapture={() => setFocused(true)}
        onBlurCapture={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
        <div className="atlas-toolbar">
          <SegmentedTabs aria-label="选择旅行灵感示例" tabs={tabs} value={sceneId} onChange={selectScene} className="atlas-scene-tabs" />
        </div>
        <div className="atlas-examples" role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${sceneId}-tab`}>
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
        </div>
      </aside>
    </>
  );
};
