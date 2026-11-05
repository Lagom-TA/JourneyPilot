import { useState, useEffect, useCallback } from 'react';
import { getPreferenceOptions, getUserProfile } from '../api/profile';
import { listMemoryFacts } from '../api/memory';
import { getDefaultOrigin } from '../api/defaultOrigin';
import { describeRequestFailure, type RequestFailure } from '../../../lib/requestFailureMessage';
import { readPreferenceSelections, type PreferenceSelections } from '../model/preferenceGroups';
import { type MemoryFactItem } from '../types/memory';
import { type PreferenceOptionGroup } from '../types/profile';
import { type PlaceIdentity } from '../../travel/types/planner';

export function usePreferenceResources() {
  const [groups, setGroups] = useState<PreferenceOptionGroup[]>([]);
  const [selections, setSelections] = useState<PreferenceSelections>({});
  const [facts, setFacts] = useState<MemoryFactItem[]>([]);
  const [defaultOrigin, setDefaultOrigin] = useState<PlaceIdentity | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<RequestFailure | null>(null);
  const [profileError, setProfileError] = useState<RequestFailure | null>(null);
  const [originError, setOriginError] = useState<RequestFailure | null>(null);
  const [factsError, setFactsError] = useState<RequestFailure | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    const [options, profile, memory, origin] = await Promise.allSettled([
      getPreferenceOptions(), getUserProfile(), listMemoryFacts(), getDefaultOrigin(),
    ]);
    if (options.status === 'rejected') {
      setLoadError(describeRequestFailure(options.reason, '读取', '偏好选项'));
    } else {
      setGroups(options.value);
      setProfileError(profile.status === 'rejected' ? describeRequestFailure(profile.reason, '读取', '旅行偏好') : null);
      if (profile.status === 'fulfilled') setSelections(readPreferenceSelections(options.value, profile.value));
      setFactsError(memory.status === 'rejected' ? describeRequestFailure(memory.reason, '读取', '旅行记忆') : null);
      if (memory.status === 'fulfilled') setFacts(memory.value.facts);
      setOriginError(origin.status === 'rejected' ? describeRequestFailure(origin.reason, '读取', '常用出发地') : null);
      if (origin.status === 'fulfilled') setDefaultOrigin(origin.value);
    }
    setLoading(false);
  }, []);
  const refreshFacts = useCallback(async () => {
    try {
      setFacts((await listMemoryFacts()).facts);
      setFactsError(null);
    } catch (err) { setFactsError(describeRequestFailure(err, '读取', '旅行记忆')); }
  }, []);
  const refreshProfile = async () => {
    try {
      setSelections(readPreferenceSelections(groups, await getUserProfile()));
      setProfileError(null);
    } catch (err) { setProfileError(describeRequestFailure(err, '读取', '旅行偏好')); }
  };
  const refreshOrigin = async () => {
    try {
      setDefaultOrigin(await getDefaultOrigin());
      setOriginError(null);
    } catch (err) { setOriginError(describeRequestFailure(err, '读取', '常用出发地')); }
  };
  useEffect(() => { void loadAll(); }, [loadAll]);
  return { groups, selections, setSelections, facts, loading, defaultOrigin, setDefaultOrigin, loadError, loadAll, profileError, originError, factsError, refreshFacts, refreshProfile, refreshOrigin };
}
