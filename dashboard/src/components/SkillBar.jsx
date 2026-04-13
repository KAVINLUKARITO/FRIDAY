function clampPercent(value) {
  return Math.max(0, Math.min(100, Math.round((value || 0) * 100)));
}

export default function SkillBar({ skill, mastery }) {
  const percent = clampPercent(mastery);

  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="mb-3 flex items-center justify-between gap-4">
        <p className="text-sm font-medium text-white">{skill}</p>
        <p className="mono text-xs uppercase tracking-[0.25em] text-cyan">{percent}%</p>
      </div>
      <div className="h-3 overflow-hidden rounded-full border border-cyan/20 bg-slate-950/70">
        <div
          className="h-full rounded-full bg-cyan shadow-[0_0_18px_rgba(60,246,208,0.6)] transition-all duration-700"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
