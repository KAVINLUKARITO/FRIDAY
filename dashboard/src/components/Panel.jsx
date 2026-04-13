export default function Panel({ title, eyebrow, children, className = "" }) {
  return (
    <section className={`rounded-3xl border border-white/10 bg-panel/80 p-5 shadow-glow backdrop-blur ${className}`}>
      <div className="mb-4 flex items-center justify-between">
        <div>
          {eyebrow ? <p className="mono text-xs uppercase tracking-[0.35em] text-cyan/80">{eyebrow}</p> : null}
          <h2 className="text-xl font-semibold text-white">{title}</h2>
        </div>
      </div>
      {children}
    </section>
  );
}
