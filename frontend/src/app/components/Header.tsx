"use client";

import { TabEnum } from "@/app/enums/tabs";

interface HeaderProps {
  currentTab: TabEnum;
  setTab: (tab: TabEnum) => void;
}

export const Header = ({ currentTab, setTab }: HeaderProps) => {
  return (
    <header className="bg-deepdark border-b border-coffee px-3 py-2 sm:px-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 sm:gap-6">
        <div className="flex min-w-0 shrink-0 items-center gap-2 sm:gap-3">
          <span className="text-xs font-bold uppercase tracking-widest text-gold sm:text-sm">
            Draft Gap
          </span>
          <span className="hidden text-stone text-xs sm:inline">·</span>
          <span className="hidden text-2xs uppercase tracking-widest text-soulsilver/60 sm:inline md:inline">
            LoL Esports Betting Simulator
          </span>
        </div>
        <nav
          className="flex min-w-0 flex-1 basis-full flex-wrap items-center gap-3 sm:basis-auto sm:gap-6"
          aria-label="Main navigation"
        >
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
      </div>
    </header>
  );
};
