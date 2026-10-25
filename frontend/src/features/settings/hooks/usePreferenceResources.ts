import { useState, useEffect } from 'react';
import { getPreferenceOptions, getUserProfile } from "../api/profile";
import { listMemoryFacts } from "../api/memory";
import { getDefaultOrigin } from "../api/defaultOrigin";
import { describeRequestFailure, type RequestFailure } from "../../../lib/requestFailureMessage";
import { readPreferenceSelections, type PreferenceSelections } from "../model/preferenceGroups";
import { type MemoryFactItem } from "../types/memory";
import { type PreferenceOptionGroup } from "../types/profile";
import { type PlaceIdentity } from "../../travel/types/planner";
export function usePreferenceResources(setStatusMessage: (message: string | null) => void) {
    const [groups, setGroups] = useState<PreferenceOptionGroup[]>([]);
    const [selections, setSelections] = useState<PreferenceSelections>({});
    const [facts, setFacts] = useState<MemoryFactItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [factsUnavailable, setFactsUnavailable] = useState(false);
    const [defaultOrigin, setDefaultOrigin] = useState<PlaceIdentity | null>(null);
    const [loadError, setLoadError] = useState<RequestFailure | null>(null);
    const loadAll = async () => {
        setLoading(true);
        setLoadError(null);
        try {
            const [optionsResult, profileResult, factsResult, originResult] = await Promise.allSettled([
                getPreferenceOptions(),
                getUserProfile(),
                listMemoryFacts(),
                getDefaultOrigin(),
            ]);
            if (optionsResult.status === 'rejected') {
                setLoadError(describeRequestFailure(optionsResult.reason, '读取', '偏好选项'));
                setGroups([]);
                setSelections({});
                setFacts([]);
                setFactsUnavailable(true);
                return;
            }
            if (profileResult.status === 'rejected' &&
                factsResult.status === 'rejected' &&
                originResult.status === 'rejected') {
                setLoadError(describeRequestFailure(profileResult.reason, '读取', '你的偏好'));
                setGroups([]);
                setSelections({});
                setFacts([]);
                setFactsUnavailable(true);
                return;
            }
            setGroups(optionsResult.value);
            setSelections(readPreferenceSelections(optionsResult.value, profileResult.status === 'fulfilled' ? profileResult.value : null));
            if (factsResult.status === 'fulfilled') {
                setFacts(factsResult.value.facts);
                setFactsUnavailable(false);
            }
            else {
                setFacts([]);
                setFactsUnavailable(true);
            }
            if (originResult.status === 'fulfilled')
                setDefaultOrigin(originResult.value);
            if (profileResult.status === 'rejected' || factsResult.status === 'rejected') {
                setStatusMessage('部分记忆数据暂时不可用。');
            }
        }
        finally {
            setLoading(false);
        }
    };
    const refreshFacts = async () => {
        try {
            const factList = await listMemoryFacts();
            setFacts(factList.facts);
            setFactsUnavailable(false);
        }
        catch (err) {
            setFactsUnavailable(true);
            setStatusMessage(describeRequestFailure(err, '读取', '记忆列表').message);
        }
    };
    useEffect(() => {
        void loadAll();
    }, []);
    return { groups, selections, setSelections, facts, loading, factsUnavailable, defaultOrigin, setDefaultOrigin, loadError, loadAll, refreshFacts };
}
