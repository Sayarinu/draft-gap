import { TabEnum } from "@/app/enums/tabs";
import { TabButton } from "./TabButton";

interface TabGroupProps {
  selectedTab: TabEnum;
  setSelectedTab: React.Dispatch<React.SetStateAction<TabEnum>>;
}

export const TabGroup = ({ selectedTab, setSelectedTab }: TabGroupProps) => {
  return (
    <div className="flex w-full justify-end gap-2 p-2">
      {Object.values(TabEnum).map((tab) => (
        <TabButton
          key={tab}
          tab={tab}
          isActiveTab={selectedTab === tab}
          setTab={setSelectedTab}
        />
      ))}
    </div>
  );
};
