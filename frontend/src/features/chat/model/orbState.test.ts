import { describe, expect, it } from "vitest";
import { orbStateForAgent } from "./orbState";

describe('orbStateForAgent', () => {
    it('内部名与显示名落在同一个球上', () => {
        expect(orbStateForAgent('transport_researcher')).toBe('connecting');
        expect(orbStateForAgent('交通查询')).toBe('connecting');
        expect(orbStateForAgent('itinerary_planner')).toBe('weaving');
        expect(orbStateForAgent('行程规划')).toBe('weaving');
    });
    it('补研轮次后缀不改变球', () => {
        expect(orbStateForAgent('destination_researcher_r2')).toBe('searching');
        expect(orbStateForAgent('目的地调研（第2轮补充）')).toBe('searching');
    });
    it('未登记但有阶段的节点退回阶段默认；完全未知退回 working', () => {
        expect(orbStateForAgent('completely_unknown_node')).toBe('working');
    });
});