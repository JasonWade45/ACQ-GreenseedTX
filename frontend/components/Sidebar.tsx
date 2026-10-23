"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const GROUPS: { heading: string; items: { href: string; label: string; icon: string }[] }[] = [
  {
    heading: "Workspace",
    items: [
      { href: "/", label: "Dashboard", icon: "▦" },
      { href: "/leads", label: "Leads", icon: "☰" },
      { href: "/followups", label: "Daily Follow-ups", icon: "◎" },
      { href: "/appointments", label: "Appointments", icon: "▤" },
    ],
  },
  {
    heading: "Data",
    items: [
      { href: "/import", label: "Import Center", icon: "⇪" },
      { href: "/reports", label: "Reports", icon: "◫" },
      { href: "/insights", label: "AI Insights", icon: "✦" },
    ],
  },
  {
    heading: "System",
    items: [
      { href: "/sync", label: "Sync Status", icon: "⟳" },
      { href: "/settings", label: "Settings", icon: "⚙" },
    ],
  },
];

function SproutMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <span
      className={`flex shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 shadow-sm shadow-brand-950/40 ${className}`}
    >
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
        <path d="M12 21v-8" stroke="#ffffff" strokeWidth="1.8" strokeLinecap="round" />
        <path
          d="M12 13C12 8.6 8.6 5.2 4.2 5.2c0 4.4 3.4 7.8 7.8 7.8z"
          fill="#ffffff"
          fillOpacity="0.92"
        />
        <path
          d="M12 13c0-3.8 2.9-6.7 6.7-6.7 0 3.8-2.9 6.7-6.7 6.7z"
          fill="#ffffff"
          fillOpacity="0.65"
        />
      </svg>
    </span>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const nav = (
    <nav className="flex h-full flex-col overflow-y-auto p-3">
      <div className="mb-5 flex items-center gap-3 px-2 pt-1">
        <SproutMark />
        <div className="min-w-0">
          <div className="truncate text-[15px] font-bold tracking-tight text-white">GreenSeedTX</div>
          <div className="truncate text-[11px] text-brand-300/80">Acquisitions Assistant</div>
        </div>
      </div>

      {GROUPS.map((group) => (
        <div key={group.heading} className="mb-4">
          <div className="mb-1 px-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-white/35">
            {group.heading}
          </div>
          <div className="space-y-0.5">
            {group.items.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className={`relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${
                    active
                      ? "bg-brand-600 font-semibold text-white shadow-sm shadow-brand-950/50"
                      : "text-white/65 hover:bg-white/[0.07] hover:text-white"
                  }`}
                >
                  <span
                    className={`w-4 text-center text-xs ${active ? "opacity-90" : "opacity-60"}`}
                  >
                    {item.icon}
                  </span>
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>
      ))}

      <div className="mt-auto space-y-2 pt-4">
        <div className="rounded-lg border-l-2 border-brand-500 bg-white/[0.05] p-3 text-[11px] leading-relaxed text-white/60">
          This application <span className="font-semibold text-white">never sends messages, emails or calls</span> to
          sellers. Drafts are for human review only.
        </div>
        <div className="px-2 text-[10px] uppercase tracking-wider text-white/30">
          GreenSeedTX LLC · Wm. K. Chaisson
        </div>
      </div>
    </nav>
  );

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed left-3 top-3 z-40 rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-sm shadow-sm lg:hidden"
        aria-label="Open navigation"
      >
        ☰ Menu
      </button>
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-64 bg-brand-950">{nav}</aside>
        </div>
      )}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-black/30 bg-gradient-to-b from-brand-950 via-[#04150f] to-[#020d09] lg:block">
        {nav}
      </aside>
    </>
  );
}
