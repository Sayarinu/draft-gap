import { TabEnum } from "@/app/enums/tabs";

interface TabButtonProps {
  tab: TabEnum;
  setTab: (tab: TabEnum) => void;
  isActiveTab: boolean;
}

export const TabButton = ({ tab, setTab, isActiveTab }: TabButtonProps) => {
  return (
    <button
      className={`px-4 py-2 rounded-md border ${isActiveTab ? "bg-gold text-deepdark" : "bg-deepdark text-gold"}`}
      onClick={() => setTab(tab)}
    >
      {tab}
    </button>
  );
};
