import { SignInButton, SignUpButton, SignedIn, SignedOut, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import Head from "next/head";
import { useEffect, useMemo, useState } from "react";

export default function Home() {
  // Landing page "Market snapshot" table: fetch a few tickers from the backend (Polygon happens server-side).
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const defaultSymbols = useMemo(() => ["AAPL", "MSFT", "SPY", "NVDA"], []);
  const [quotes, setQuotes] = useState<Array<{ symbol: string; price?: number | null; as_of?: string | null }>>([]);
  const [quotesStatus, setQuotesStatus] = useState<"idle" | "loading" | "loaded" | "error">("idle");

  useEffect(() => {
    let isMounted = true;
    const run = async () => {
      try {
        setQuotesStatus("loading");
        const qs = encodeURIComponent(defaultSymbols.join(","));
        const res = await fetch(`${apiBaseUrl}/api/public/quotes?symbols=${qs}`);
        if (!res.ok) throw new Error(`quotes_fetch_failed_${res.status}`);
        const data = await res.json();
        if (!isMounted) return;
        setQuotes(Array.isArray(data?.quotes) ? data.quotes : []);
        setQuotesStatus("loaded");
      } catch {
        if (!isMounted) return;
        setQuotesStatus("error");
      }
    };
    run();
    return () => {
      isMounted = false;
    };
  }, [apiBaseUrl, defaultSymbols]);

  return (
    <>
      <Head>
        <title>Alex AI Financial Advisor - Intelligent Portfolio Management</title>
      </Head>
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-gray-50">
      {/* Navigation */}
      <nav className="px-8 py-6 bg-white shadow-sm">
        <div className="max-w-7xl mx-auto flex justify-between items-center">
          <div className="text-2xl font-bold text-dark">
            <span className="text-primary">AI</span> Financial Advisor
          </div>
          <div className="flex gap-4">
            <SignedOut>
              <SignInButton mode="modal">
                <button className="px-6 py-2 text-primary border border-primary rounded-lg hover:bg-primary hover:text-white transition-colors">
                  Sign In
                </button>
              </SignInButton>
              <SignUpButton mode="modal">
                <button className="px-6 py-2 bg-primary text-white rounded-lg hover:bg-blue-600 transition-colors">
                  Get Started
                </button>
              </SignUpButton>
            </SignedOut>
            <SignedIn>
              <div className="flex items-center gap-4">
                <Link href="/dashboard">
                  <button className="px-6 py-2 bg-ai-accent text-white rounded-lg hover:bg-purple-700 transition-colors">
                    Go to Dashboard
                  </button>
                </Link>
                <UserButton afterSignOutUrl="/" />
              </div>
            </SignedIn>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="px-8 py-20">
        <div className="max-w-7xl mx-auto text-center">
          <h1 className="text-5xl font-bold text-dark mb-6">
            Your AI-Powered Financial Future
          </h1>
          <p className="text-xl text-gray-600 mb-8 max-w-3xl mx-auto">
            Experience the power of autonomous AI agents working together to analyze your portfolio, 
            plan your retirement, and optimize your investments.
          </p>
          <div className="flex gap-6 justify-center">
            <SignedOut>
              <SignUpButton mode="modal">
                <button className="px-8 py-4 bg-ai-accent text-white text-lg rounded-lg hover:bg-purple-700 transition-colors shadow-lg">
                  Start Your Analysis
                </button>
              </SignUpButton>
            </SignedOut>
            <SignedIn>
              <Link href="/dashboard">
                <button className="px-8 py-4 bg-ai-accent text-white text-lg rounded-lg hover:bg-purple-700 transition-colors shadow-lg">
                  Open Dashboard
                </button>
              </Link>
            </SignedIn>
          </div>
        </div>
      </section>

      {/* Market snapshot (landing page stock price table) */}
      <section className="px-8 pb-10">
        <div className="max-w-4xl mx-auto overflow-hidden rounded-3xl border border-gray-200/70 bg-white shadow-lg ring-1 ring-black/5">
          <div className="relative px-8 py-6">
            <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-primary/10 via-ai-accent/10 to-primary/5" />
            <div className="relative flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full bg-white/70 px-3 py-1 text-xs font-semibold text-primary ring-1 ring-primary/20">
                  Snapshot
                </div>
                <h2 className="mt-3 text-2xl font-bold tracking-tight text-dark">Market snapshot</h2>
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-gray-600">
                  A quick look at a few tickers using <span className="font-medium text-gray-700">previous close</span> prices (may be delayed).
                </p>
              </div>

              <div className="flex items-center gap-2 self-start rounded-full bg-white/80 px-3 py-2 text-xs text-gray-600 ring-1 ring-gray-200/70">
                {quotesStatus === "loading" && (
                  <>
                    <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                    <span>Updating…</span>
                  </>
                )}
                {quotesStatus === "loaded" && <span className="text-gray-700">Up to date</span>}
                {quotesStatus === "error" && <span className="text-red-600">Couldn’t load prices</span>}
              </div>
            </div>
          </div>

          <div className="px-2 pb-2">
            <div className="overflow-hidden rounded-2xl border border-gray-100 bg-white">
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="bg-gradient-to-b from-gray-50 to-white text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                    <tr>
                      <th className="px-6 py-4">Ticker</th>
                      <th className="px-6 py-4 text-right">Price</th>
                      <th className="px-6 py-4 text-right">As of</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {(quotes.length ? quotes : defaultSymbols.map((s) => ({ symbol: s, price: null, as_of: null }))).map((q) => {
                      const isLoadingRow = quotesStatus === "loading" && quotes.length === 0;
                      return (
                        <tr key={q.symbol} className="text-sm transition-colors hover:bg-gray-50/70">
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary/15 to-ai-accent/15 text-xs font-bold text-dark ring-1 ring-black/5">
                                {q.symbol.slice(0, 1)}
                              </div>
                              <div>
                                <div className="font-semibold tracking-wide text-dark">{q.symbol}</div>
                                <div className="text-xs text-gray-500">US equity</div>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 text-right">
                            {typeof q.price === "number" ? (
                              <span className="text-base font-semibold tabular-nums text-dark">${q.price.toFixed(2)}</span>
                            ) : isLoadingRow ? (
                              <span className="inline-block h-5 w-24 animate-pulse rounded-md bg-gray-100" />
                            ) : (
                              <span className="text-sm font-medium text-gray-400">—</span>
                            )}
                          </td>
                          <td className="px-6 py-4 text-right text-gray-600 tabular-nums">
                            {q.as_of ? (
                              <span>{q.as_of}</span>
                            ) : isLoadingRow ? (
                              <span className="inline-block h-5 w-28 animate-pulse rounded-md bg-gray-100" />
                            ) : (
                              <span className="text-sm font-medium text-gray-400">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="px-8 py-20 bg-white">
        <div className="max-w-7xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-dark mb-12">
            Meet Your AI Advisory Team
          </h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-8">
            <div className="text-center p-6 rounded-xl hover:shadow-lg transition-shadow">
              <div className="text-4xl mb-4">🎯</div>
              <h3 className="text-xl font-semibold text-ai-accent mb-2">Financial Planner</h3>
              <p className="text-gray-600">Coordinates your complete financial analysis with intelligent orchestration</p>
            </div>
            <div className="text-center p-6 rounded-xl hover:shadow-lg transition-shadow">
              <div className="text-4xl mb-4">📊</div>
              <h3 className="text-xl font-semibold text-primary mb-2">Portfolio Analyst</h3>
              <p className="text-gray-600">Deep analysis of holdings, performance metrics, and risk assessment</p>
            </div>
            <div className="text-center p-6 rounded-xl hover:shadow-lg transition-shadow">
              <div className="text-4xl mb-4">📈</div>
              <h3 className="text-xl font-semibold text-success mb-2">Chart Specialist</h3>
              <p className="text-gray-600">Visualizes your portfolio composition with interactive charts</p>
            </div>
            <div className="text-center p-6 rounded-xl hover:shadow-lg transition-shadow">
              <div className="text-4xl mb-4">🎯</div>
              <h3 className="text-xl font-semibold text-accent mb-2">Retirement Planner</h3>
              <p className="text-gray-600">Projects your retirement readiness with Monte Carlo simulations</p>
            </div>
          </div>
        </div>
      </section>

      {/* Benefits Section */}
      <section className="px-8 py-20 bg-gradient-to-r from-primary/10 to-ai-accent/10">
        <div className="max-w-7xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-dark mb-12">
            Enterprise-Grade AI Advisory
          </h2>
          <div className="grid md:grid-cols-3 gap-8">
            <div className="bg-white p-8 rounded-xl shadow-md">
              <div className="text-accent text-2xl mb-4">⚡</div>
              <h3 className="text-xl font-semibold mb-3">Real-Time Analysis</h3>
              <p className="text-gray-600">Watch AI agents collaborate in parallel to analyze your complete financial picture</p>
            </div>
            <div className="bg-white p-8 rounded-xl shadow-md">
              <div className="text-accent text-2xl mb-4">🔒</div>
              <h3 className="text-xl font-semibold mb-3">Bank-Level Security</h3>
              <p className="text-gray-600">Your data is protected with enterprise security and row-level access controls</p>
            </div>
            <div className="bg-white p-8 rounded-xl shadow-md">
              <div className="text-accent text-2xl mb-4">📊</div>
              <h3 className="text-xl font-semibold mb-3">Comprehensive Reports</h3>
              <p className="text-gray-600">Detailed markdown reports with interactive charts and retirement projections</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="px-8 py-20 bg-dark text-white">
        <div className="max-w-4xl mx-auto text-center">
          <h2 className="text-3xl font-bold mb-6">
            Ready to Transform Your Financial Future?
          </h2>
          <p className="text-xl mb-8 opacity-90">
            Join thousands of investors using AI to optimize their portfolios
          </p>
          <SignUpButton mode="modal">
            <button className="px-8 py-4 bg-accent text-dark font-semibold text-lg rounded-lg hover:bg-yellow-500 transition-colors shadow-lg">
              Get Started Free
            </button>
          </SignUpButton>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-8 py-6 bg-gray-900 text-gray-400 text-center text-sm">
        <p>© 2026 AI Financial Advisor. All rights reserved.</p>
        <p className="mt-2">
          This AI-generated advice has not been vetted by a qualified financial advisor and should not be used for trading decisions. 
          For informational purposes only.
        </p>
      </footer>
    </div>
    </>
  );
}