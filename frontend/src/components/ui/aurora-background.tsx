// 背景：网格 + 双辉光球（Aceternity 风格氛围层）
export function AuroraBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-ink">
      {/* 细网格 */}
      <div
        className="absolute inset-0 opacity-[0.18]"
        style={{
          backgroundImage:
            'linear-gradient(to right, #1c2533 1px, transparent 1px), linear-gradient(to bottom, #1c2533 1px, transparent 1px)',
          backgroundSize: '44px 44px',
          maskImage: 'radial-gradient(ellipse 80% 60% at 50% 0%, #000 50%, transparent 100%)',
        }}
      />
      {/* 辉光球 */}
      <div className="absolute -top-40 left-1/4 h-[420px] w-[620px] -translate-x-1/2 rounded-full bg-indigo-600/25 blur-[120px]" />
      <div className="absolute top-10 right-0 h-[360px] w-[480px] rounded-full bg-cyan-500/15 blur-[120px]" />
      <div className="absolute bottom-0 left-0 h-[300px] w-[400px] rounded-full bg-fuchsia-600/10 blur-[120px]" />
    </div>
  )
}
