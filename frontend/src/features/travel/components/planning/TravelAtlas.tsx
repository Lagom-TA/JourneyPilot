import { AnimatePresence, m, useReducedMotion } from 'motion/react';
import { ArrowRight } from 'lucide-react';
import React from 'react';
import islandArtwork from '../../../../assets/home/island.webp';
import jiangnanArtwork from '../../../../assets/home/jiangnan.webp';
import northwestArtwork from '../../../../assets/home/northwest.webp';
import southwestArtwork from '../../../../assets/home/southwest.webp';
import ticketPaper from '../../../../assets/paper/ticket-main.webp';
import luggagePaper from '../../../../assets/paper/tag-luggage.webp';
import luggageWidePaper from '../../../../assets/paper/tag-luggage-wide.webp';
import { SegmentedTabs, type SegmentedTab } from '../../../../components/ui/SegmentedTabs';
import { duration, easing } from '../../../../lib/motion';
import { ATLAS_SCENES, type AtlasScene, type AtlasSceneId } from './TravelAtlasScenes';

const ARTWORK: Record<AtlasSceneId, string> = {
  island: islandArtwork,
  jiangnan: jiangnanArtwork,
  northwest: northwestArtwork,
  southwest: southwestArtwork,
};

export const TravelAtlas: React.FC<{
  onUseExample: (scene: AtlasScene) => void;
}> = ({ onUseExample }) => {
  const reducedMotion = useReducedMotion();
  const tabsId = React.useId();
  const [sceneId, setSceneId] = React.useState<AtlasSceneId>('northwest');
  const [artworkSceneId, setArtworkSceneId] = React.useState<AtlasSceneId>('northwest');
  const currentIndex = ATLAS_SCENES.findIndex((item) => item.id === sceneId);
  const scenes = [ATLAS_SCENES[currentIndex]!, ATLAS_SCENES[(currentIndex + 1) % ATLAS_SCENES.length]!];

  const tabs = React.useMemo<ReadonlyArray<SegmentedTab<AtlasSceneId>>>(() => ATLAS_SCENES.map((item) => ({
    id: item.id,
    label: item.tab,
    testId: `atlas-tab-${item.id}`,
    domId: `${tabsId}-${item.id}-tab`,
    panelId: `${tabsId}-panel`,
  })), [tabsId]);

  React.useEffect(() => {
    let active = true;
    const artwork = new Image();
    artwork.src = ARTWORK[sceneId];
    void artwork.decode().then(() => {
      if (active) setArtworkSceneId(sceneId);
    }).catch(() => {
      // 背景未就绪时保留当前风景，灵感填入仍可使用。
    });
    return () => { active = false; };
  }, [sceneId]);

  return (
    <>
      <div className="home-landscape" aria-hidden="true">
        <AnimatePresence initial={false}>
          <m.div
            key={artworkSceneId}
            className="atlas-scene"
            initial={{ clipPath: reducedMotion ? 'none' : 'inset(0 0 0 100%)' }}
            animate={{ clipPath: 'inset(0 0 0 0%)' }}
            exit={{ opacity: 0 }}
            transition={{ duration: reducedMotion ? 0 : duration.emphasis, ease: easing.decelerate }}
          >
            <img className="atlas-artwork" src={ARTWORK[artworkSceneId]} alt="" decoding="async" fetchPriority="high" />
          </m.div>
        </AnimatePresence>
      </div>
      <aside className="travel-atlas" aria-label="旅行灵感" data-scene={sceneId} data-testid="travel-atlas">
        <div className="atlas-examples" role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${sceneId}-tab`}>
          {scenes.map((scene, index) => (
            <button
              key={scene.id}
              type="button"
              className={`atlas-example-card ${index === 0 ? 'is-primary' : 'is-secondary'}`}
              aria-label={`用这个灵感填入规划：${scene.cardTitle}`}
              data-testid={index === 0 ? 'atlas-use-example' : 'atlas-use-alternate'}
              onClick={() => onUseExample(scene)}
            >
              {index === 0 ? (
                <img className="atlas-paper" src={ticketPaper} alt="" aria-hidden="true" draggable={false} />
              ) : (
                <picture className="atlas-paper-frame" aria-hidden="true">
                  <source media="(width < 640px)" srcSet={luggageWidePaper} />
                  <img className="atlas-paper" src={luggagePaper} alt="" draggable={false} />
                </picture>
              )}
              <span className="atlas-example-body">
                <span className="atlas-example-title">{scene.tab}</span>
                <span className="atlas-example-caption">
                  <span>{scene.destinations.map((place) => place.name).join(' · ')} <span className="atlas-example-duration">/ {scene.days} 日</span></span>
                  <span className="atlas-example-action">填入 {index === 1 && <ArrowRight size={14} aria-hidden="true" />}</span>
                </span>
              </span>
              {index === 0 && <ArrowRight className="atlas-ticket-arrow" size={18} aria-hidden="true" />}
            </button>
          ))}
        </div>
        <SegmentedTabs
          aria-label="选择旅行灵感示例"
          tabs={tabs}
          value={sceneId}
          onChange={setSceneId}
          className="atlas-scene-tabs"
        />
      </aside>
    </>
  );
};
