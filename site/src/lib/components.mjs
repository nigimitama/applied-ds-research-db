// 共通の小さなHTML断片ではなく、Astroコンポーネントに渡す補助関数
import { AXES } from "./data.mjs";

export const base = () => import.meta.env.BASE_URL.replace(/\/$/, "");

export function articleTags(a, tax) {
  const out = [];
  for (const axis of Object.keys(AXES))
    for (const id of a.tags?.[axis] || []) out.push({ axis, id, label: tax[axis][id]?.ja ?? id });
  return out;
}
