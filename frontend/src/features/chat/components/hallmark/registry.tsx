import { type ContextReport } from "../../types/context";
import { type CostLedgerView, costLedgerBlurb } from "../../model/costLedger";
import { ContextLens } from "./ContextLens";
import { CostLedger } from "./CostLedger";
import React from 'react';
export type HallmarkGlyph = 'context' | 'cost';
export interface HallmarkEntry<Data> {
    symbol: string;
    ariaLabel: string;
    blurb: (data: Data) => string;
    render: (data: Data) => React.ReactNode;
}
export const HALLMARK_REGISTRY: {
    context: HallmarkEntry<ContextReport>;
    cost: HallmarkEntry<CostLedgerView>;
} = {
    context: {
        symbol: '◈',
        ariaLabel: '本次参考的信息',
        blurb: () => '这轮回答参考了已知的旅行信息',
        render: (data) => <ContextLens report={data}/>,
    },
    cost: {
        symbol: '¤',
        ariaLabel: '本轮模型用量',
        blurb: costLedgerBlurb,
        render: (data) => <CostLedger view={data}/>,
    },
};
