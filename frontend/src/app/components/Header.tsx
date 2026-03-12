"use client";

import { TabEnum } from "@/app/enums/tabs";

interface HeaderProps {
  currentTab: TabEnum;
  setTab: (tab: TabEnum) => void;
}

export const Header = ({ currentTab, setTab }: HeaderProps) => {
  return (
    <header className="bg-deepdark flex items-center px-4 py-2 border-b border-coffee">
      <div className="flex items-center gap-3 flex-1">
        <span className="text-sm text-gold font-bold tracking-widest uppercase">Draft Gap</span>
        <span className="text-stone text-xs">·</span>
        <span className="text-2xs text-soulsilver/60 uppercase tracking-widest">
          LoL Esports Betting Simulator
        </span>
      </div>
      <nav className="flex items-center gap-6" aria-label="Main navigation">
        {Object.values(TabEnum).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setTab(tab)}
            className={`text-2xs font-bold uppercase tracking-widest transition-colors ${
              currentTab === tab
                ? "text-gold border-b border-gold pb-px"
                : "text-taupe hover:text-cream"
            }`}
          >
            {tab}
          </button>
        ))}
      </nav>
    </header>
  );
};
