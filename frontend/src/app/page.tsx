"use client";

import { useState } from "react";
import BettingTable from "./components/Table/BettingTable";
import ResultTable from "./components/Table/ResultTable";
import { TabGroup } from "./components/UI/Tabs/TabGroup";
import { TabEnum } from "./enums/tabs";

export default function Home() {
  const [tab, setTab] = useState<TabEnum>(TabEnum.Upcoming);

  return (
    <div className="flex flex-col flex-1 bg-concrete">
      <div className="flex border-t border-b border-soulsilver/50">
        <TabGroup setSelectedTab={setTab} selectedTab={tab} />
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === TabEnum.Upcoming ? <BettingTable /> : <ResultTable />}
      </div>
    </div>
  );
}
