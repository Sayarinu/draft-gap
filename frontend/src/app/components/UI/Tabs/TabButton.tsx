import { TabEnum } from "@/app/enums/tabs";

interface TabButtonProps {
  tab: TabEnum;
  setTab: (tab: TabEnum) => void;
  isActiveTab: boolean;
}

export const TabButton = ({ tab, setTab, isActiveTab }: TabButtonProps) => {
  return (
    <button
      className={`rounded-md border px-4 py-2 ${
        isActiveTab
          ? "border-gold bg-gold/10 text-gold"
          : "border-coffee bg-deepdark text-taupe hover:text-cream"
      }`}
      onClick={() => setTab(tab)}
    >
      {tab}
    </button>
  );
};
