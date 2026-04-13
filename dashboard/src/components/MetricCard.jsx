export default function MetricCard({ label, value, tone = "cyan", detail }) {
  const toneClass = {
    cyan: "text-cyan",
    blue: "text-blue",
    danger: "text-danger",
    warn: "text-warn",
  }[tone] || "text-cyan";

  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <p className="mono text-xs uppercase tracking-[0.3em] text-slate-400">{label}</p>
      <p className={`mt-3 text-3xl font-semibold ${toneClass}`}>{value}</p>
      {detail ? <p className="mt-2 text-sm text-slate-400">{detail}</p> : null}
    </div>
  );
}
