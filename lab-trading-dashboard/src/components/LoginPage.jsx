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
      {/* Animated background */}
      <div className="absolute inset-0 bg-gradient-to-br from-[#0a0a12] via-[#0d0f18] to-[#0a0e1a]" />
      {/* Moving grid */}
      <div
        className="absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage: `linear-gradient(rgba(255,255,255,.15) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,.15) 1px, transparent 1px)`,
          backgroundSize: "48px 48px",
          animation: "login-grid-flow 20s linear infinite",
        }}
      />
      {/* Animated gradient orbs */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[700px] h-[450px] rounded-full blur-[140px] pointer-events-none bg-teal-500/20"
        style={{ animation: "login-gradient-shift 12s ease-in-out infinite" }}
      />
      <div
        className="absolute bottom-1/3 right-0 w-[450px] h-[350px] rounded-full blur-[120px] pointer-events-none bg-cyan-500/15"
        style={{ animation: "login-float 18s ease-in-out infinite" }}
      />
      <div
        className="absolute top-1/3 left-0 w-[350px] h-[400px] rounded-full blur-[100px] pointer-events-none bg-teal-400/10"
        style={{ animation: "login-float-slow 22s ease-in-out infinite" }}
      />

      {/* Login card with clear background */}
      <div className="relative w-full max-w-[420px]">
        <div className="rounded-2xl border border-white/10 bg-[#0e1015]/95 shadow-2xl shadow-black/50 backdrop-blur-xl overflow-hidden">
          {/* Top accent bar */}
          <div className="h-1 bg-gradient-to-r from-teal-500 via-cyan-400 to-teal-500" />

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
