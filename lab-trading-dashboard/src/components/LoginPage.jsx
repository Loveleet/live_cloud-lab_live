import React, { useState } from "react";
import { loginWithCredentials } from "../auth";
import { Mail, Lock, Shield, Loader2 } from "lucide-react";

export default function LoginPage({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await loginWithCredentials(email, password);
      onLogin();
    } catch (err) {
      setError(err?.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden bg-[#06060a] p-4">
      {/* Base gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-[#050508] via-[#0a0c14] to-[#060810]" />
      {/* Animated gradient mesh */}
      <div
        className="absolute inset-0 opacity-80"
        style={{
          background: "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(20, 184, 166, 0.25), transparent), radial-gradient(ellipse 60% 40% at 100% 100%, rgba(6, 182, 212, 0.2), transparent), radial-gradient(ellipse 50% 50% at 0% 80%, rgba(20, 184, 166, 0.15), transparent)",
          animation: "login-graphics-pulse 12s ease-in-out infinite",
        }}
      />
      {/* Moving grid with subtle pulse */}
      <div
        className="absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage: `linear-gradient(rgba(255,255,255,.2) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,.2) 1px, transparent 1px)`,
          backgroundSize: "48px 48px",
          animation: "login-grid-flow 20s linear infinite",
        }}
      />
      {/* Glowing orbs - premium motion */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[500px] rounded-full pointer-events-none bg-teal-400/30"
        style={{ filter: "blur(120px)", animation: "login-glow-pulse 8s cubic-bezier(0.45, 0, 0.55, 1) infinite", willChange: "transform, opacity" }}
      />
      <div
        className="absolute bottom-1/3 right-0 w-[500px] h-[400px] rounded-full pointer-events-none bg-cyan-400/25"
        style={{ filter: "blur(130px)", animation: "login-orb-drift 14s cubic-bezier(0.45, 0, 0.55, 1) infinite", willChange: "transform" }}
      />
      <div
        className="absolute top-1/3 left-0 w-[400px] h-[450px] rounded-full pointer-events-none bg-teal-500/20"
        style={{ filter: "blur(110px)", animation: "login-float-3d 20s cubic-bezier(0.45, 0, 0.55, 1) infinite", willChange: "transform" }}
      />
      {/* Morphing blobs */}
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] overflow-hidden pointer-events-none"
        style={{ filter: "blur(80px)", animation: "login-morph 15s ease-in-out infinite", willChange: "border-radius, opacity" }}
      >
        <div className="w-full h-full bg-gradient-to-br from-teal-500/22 to-cyan-500/18" />
      </div>
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[400px] h-[400px] overflow-hidden pointer-events-none"
        style={{ filter: "blur(60px)", animation: "login-morph 18s ease-in-out infinite 2s", willChange: "border-radius, opacity" }}
      >
        <div className="w-full h-full bg-gradient-to-tr from-cyan-500/15 to-teal-500/12" style={{ borderRadius: "inherit" }} />
      </div>

      {/* Floating particles - layer 1: static float */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
        {[...Array(14)].map((_, i) => (
          <div
            key={i}
            className="absolute rounded-full bg-teal-400/90"
            style={{
              width: 2 + (i % 3),
              height: 2 + (i % 3),
              left: `${8 + (i * 6.5) % 84}%`,
              top: `${12 + (i * 7) % 76}%`,
              animation: `login-particle-float ${4 + (i % 5)}s ease-in-out infinite`,
              animationDelay: `${i * 0.15}s`,
              willChange: "transform, opacity",
            }}
          />
        ))}
        {[...Array(10)].map((_, i) => (
          <div
            key={`c-${i}`}
            className="absolute rounded-full bg-cyan-400/80"
            style={{
              width: 1.5 + (i % 2),
              height: 1.5 + (i % 2),
              left: `${3 + (i * 10) % 94}%`,
              top: `${18 + (i * 8) % 68}%`,
              animation: `login-particle-float ${5 + (i % 4)}s ease-in-out infinite`,
              animationDelay: `${i * 0.25 + 0.3}s`,
              willChange: "transform, opacity",
            }}
          />
        ))}
        {/* Twinkle dots */}
        {[...Array(6)].map((_, i) => (
          <div
            key={`t-${i}`}
            className="absolute w-1.5 h-1.5 rounded-full bg-white/60"
            style={{
              left: `${15 + (i * 14) % 70}%`,
              top: `${25 + (i * 12) % 55}%`,
              animation: `login-twinkle ${2.5 + (i % 2)}s ease-in-out infinite`,
              animationDelay: `${i * 0.4}s`,
            }}
          />
        ))}
      </div>
      {/* Rising particles - continuous stream */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
        {[...Array(5)].map((_, i) => (
          <div
            key={`r-${i}`}
            className="absolute rounded-full bg-gradient-to-b from-transparent to-teal-400/40"
            style={{
              width: 3,
              height: 20 + (i * 4),
              left: `${20 + i * 18}%`,
              bottom: "-30px",
              animation: `login-particle-rise ${8 + (i % 3)}s linear infinite`,
              animationDelay: `${i * 1.6}s`,
              willChange: "transform, opacity",
            }}
          />
        ))}
      </div>

      {/* IT theme: 0 and 1 bubbles rising */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
        {[...Array(24)].map((_, i) => {
          const char = i % 2 === 0 ? "0" : "1";
          const left = (i * 4.2) % 100;
          const duration = 12 + (i % 5);
          const delay = (i * 0.8) % 14;
          const anim = i % 3 === 0 ? "login-binary-rise-alt" : "login-binary-rise";
          return (
            <div
              key={`bin-${i}`}
              className="absolute bottom-0 flex items-center justify-center rounded-full border border-teal-400/30 bg-teal-500/10 font-mono font-bold text-teal-400/70 backdrop-blur-sm"
              style={{
                width: 28 + (i % 3) * 6,
                height: 28 + (i % 3) * 6,
                left: `${left}%`,
                fontSize: 14 + (i % 2) * 4,
                animation: `${anim} ${duration}s ease-in-out infinite`,
                animationDelay: `${delay}s`,
                willChange: "transform, opacity",
              }}
            >
              {char}
            </div>
          );
        })}
      </div>

      {/* Code symbols floating - { } < / > */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
        {["{", "}", "</", ">", "(", ")", "[", "]"].map((sym, i) => (
          <span
            key={`sym-${i}`}
            className="absolute font-mono text-cyan-400/25 text-lg font-bold"
            style={{
              left: `${12 + (i * 11) % 78}%`,
              top: `${15 + (i * 9) % 72}%`,
              animation: "login-code-float 8s ease-in-out infinite",
              animationDelay: `${i * 0.5}s`,
            }}
          >
            {sym}
          </span>
        ))}
      </div>

      {/* Subtle scanline effect - sweeps down */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div
          className="absolute left-0 w-full h-px bg-gradient-to-r from-transparent via-teal-400/25 to-transparent"
          style={{ top: 0, animation: "login-scanline 10s linear infinite" }}
        />
      </div>

      {/* SVG graphics: animated rings and curves */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
        <svg className="absolute inset-0 w-full h-full opacity-[0.22]" viewBox="0 0 1200 800" fill="none">
          <circle cx="150" cy="120" r="180" stroke="url(#login-grad1)" strokeWidth="1.2" strokeDasharray="8 4" fill="none" style={{ animation: "login-graphics-pulse 6s ease-in-out infinite, login-ring-rotate 40s linear infinite" }} />
          <circle cx="1050" cy="680" r="220" stroke="url(#login-grad2)" strokeWidth="1" strokeDasharray="6 6" fill="none" style={{ animation: "login-graphics-pulse 8s ease-in-out infinite 1s, login-ring-rotate 50s linear infinite reverse" }} />
          <circle cx="600" cy="400" r="140" stroke="rgba(20, 184, 166, 0.2)" strokeWidth="0.8" strokeDasharray="880" strokeDashoffset="880" fill="none" style={{ animation: "login-stroke-draw 5s ease-out 0.5s forwards, login-scale-pulse 8s ease-in-out infinite 4s" }} />
          <circle cx="900" cy="150" r="120" stroke="rgba(20, 184, 166, 0.4)" strokeWidth="0.8" fill="none" style={{ animation: "login-scale-breathe 10s ease-in-out infinite" }} />
          <circle cx="200" cy="550" r="100" stroke="rgba(6, 182, 212, 0.35)" strokeWidth="0.8" fill="none" style={{ animation: "login-scale-breathe 12s ease-in-out infinite 0.5s" }} />
          <defs>
            <linearGradient id="login-grad1" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#0d9488" />
              <stop offset="50%" stopColor="#06b6d4" />
              <stop offset="100%" stopColor="#0d9488" />
            </linearGradient>
            <linearGradient id="login-grad2" x1="100%" y1="100%" x2="0%" y2="0%">
              <stop offset="0%" stopColor="#06b6d4" />
              <stop offset="50%" stopColor="#0d9488" />
              <stop offset="100%" stopColor="#06b6d4" />
            </linearGradient>
          </defs>
        </svg>
        <svg className="absolute top-0 right-0 w-[550px] h-[550px] opacity-40" viewBox="0 0 200 200" style={{ animation: "login-graphics-spin-slow 45s linear infinite" }}>
          <path d="M100 20 L180 100 L100 180 L20 100 Z" stroke="rgba(20, 184, 166, 0.25)" strokeWidth="0.6" fill="none" />
          <path d="M100 40 L160 100 L100 160 L40 100 Z" stroke="rgba(6, 182, 212, 0.2)" strokeWidth="0.5" fill="none" />
          <path d="M100 60 L140 100 L100 140 L60 100 Z" stroke="rgba(20, 184, 166, 0.15)" strokeWidth="0.4" fill="none" />
        </svg>
        <svg className="absolute bottom-0 left-0 w-[450px] h-[450px] opacity-40" viewBox="0 0 200 200" style={{ animation: "login-graphics-spin-slow 55s linear infinite reverse" }}>
          <path d="M100 20 L180 100 L100 180 L20 100 Z" stroke="rgba(6, 182, 212, 0.2)" strokeWidth="0.6" fill="none" />
          <path d="M100 50 L150 100 L100 150 L50 100 Z" stroke="rgba(20, 184, 166, 0.15)" strokeWidth="0.4" fill="none" />
        </svg>
        <svg className="absolute inset-0 w-full h-full opacity-[0.18]" viewBox="0 0 1200 800" fill="none">
          <path d="M0 400 Q300 180 600 400 T1200 400" stroke="rgba(20, 184, 166, 0.5)" strokeWidth="1" fill="none" style={{ animation: "login-float-smooth 10s ease-in-out infinite" }} />
          <path d="M0 500 Q400 280 800 500 T1200 500" stroke="rgba(6, 182, 212, 0.45)" strokeWidth="0.8" fill="none" style={{ animation: "login-float-smooth 13s ease-in-out infinite 0.5s" }} />
          <path d="M0 300 Q500 450 1200 300" stroke="rgba(20, 184, 166, 0.28)" strokeWidth="0.6" fill="none" style={{ animation: "login-float-smooth 11s ease-in-out infinite 1s" }} />
          <line x1="0" y1="200" x2="1200" y2="200" stroke="rgba(255,255,255,0.06)" strokeWidth="0.5" style={{ animation: "login-line-fade 5s ease-in-out infinite" }} />
          <line x1="0" y1="600" x2="1200" y2="600" stroke="rgba(255,255,255,0.06)" strokeWidth="0.5" style={{ animation: "login-line-fade 5s ease-in-out infinite 1s" }} />
        </svg>
        <div className="absolute top-1/4 left-1/4 w-72 h-72 border border-teal-400/20 rounded-full" style={{ animation: "login-float-3d 14s cubic-bezier(0.45, 0, 0.55, 1) infinite" }} />
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 border border-cyan-400/20 rounded-full" style={{ animation: "login-float-3d 18s cubic-bezier(0.45, 0, 0.55, 1) infinite 1s" }} />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[300px] h-[300px] border border-teal-500/15 rounded-full" style={{ animation: "login-ring-rotate 30s linear infinite" }} />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[180px] h-[180px] border border-cyan-500/10 rounded-full" style={{ animation: "login-ring-rotate 25s linear infinite reverse" }} />
      </div>

      {/* Subtle noise overlay for depth */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.03]"
        style={{
          backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
        }}
      />

      {/* Login card - entrance + glow */}
      <div className="relative w-full max-w-[420px]" style={{ animation: "login-card-enter 0.6s cubic-bezier(0.22, 1, 0.36, 1) forwards" }}>
        <div className="rounded-2xl border border-white/10 bg-[#0e1015]/95 backdrop-blur-xl overflow-hidden" style={{ animation: "login-card-glow 4s ease-in-out infinite" }}>
          {/* Animated top accent bar */}
          <div
            className="h-1 rounded-t-2xl"
            style={{
              background: "linear-gradient(90deg, #0d9488, #22d3ee, #14b8a6, #06b6d4, #0d9488)",
              backgroundSize: "200% 100%",
              animation: "login-bar-shine 4s linear infinite",
            }}
          />

          <div className="p-8 sm:p-10 bg-gradient-to-b from-[#12141a]/98 to-[#0e1118]/98">
            {/* Brand */}
            <div className="flex items-center justify-center gap-3 mb-8">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-teal-500 to-cyan-600 shadow-lg shadow-teal-500/25">
                <Shield className="w-6 h-6 text-white" strokeWidth={2.5} />
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight text-white">
                  LAB
                </h1>
                <p className="text-xs font-medium text-gray-500 tracking-widest uppercase">
                  Dashboard
                </p>
              </div>
            </div>

            <p className="text-center text-gray-400 text-sm mb-6">
              Sign in with your credentials
            </p>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label
                  htmlFor="login-email"
                  className="block text-sm font-semibold text-gray-300 mb-2"
                >
                  Email
                </label>
                <div className="relative">
                  <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 pointer-events-none" />
                  <input
                    id="login-email"
                    type="email"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      setError("");
                    }}
                    placeholder="name@company.com"
                    autoComplete="email"
                    autoFocus
                    disabled={loading}
                    className="w-full pl-12 pr-4 py-3.5 rounded-xl border border-white/10 bg-[#0a0c12] text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-teal-500/60 focus:border-teal-500/50 disabled:opacity-60 transition-all duration-200"
                  />
                </div>
              </div>

              <div>
                <label
                  htmlFor="login-password"
                  className="block text-sm font-semibold text-gray-300 mb-2"
                >
                  Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 pointer-events-none" />
                  <input
                    id="login-password"
                    type="password"
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      setError("");
                    }}
                    placeholder="••••••••"
                    autoComplete="current-password"
                    disabled={loading}
                    className="w-full pl-12 pr-4 py-3.5 rounded-xl border border-white/10 bg-[#0a0c12] text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-teal-500/60 focus:border-teal-500/50 disabled:opacity-60 transition-all duration-200"
                  />
                </div>
              </div>

              {error && (
                <div className="rounded-xl bg-red-500/10 border border-red-500/20 px-4 py-3">
                  <p className="text-sm text-red-400 font-medium">{error}</p>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full py-3.5 rounded-xl bg-gradient-to-r from-teal-500 to-cyan-600 hover:from-teal-400 hover:to-cyan-500 disabled:from-teal-700 disabled:to-cyan-800 disabled:cursor-not-allowed text-white font-semibold shadow-lg shadow-teal-500/25 hover:shadow-teal-500/40 transition-all duration-200 flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    <span>Signing in…</span>
                  </>
                ) : (
                  "Sign in"
                )}
              </button>
            </form>

            <p className="mt-6 text-center text-xs text-gray-500">
              Enter your credentials to continue
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
