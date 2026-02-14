export const Header = () => {
  return (
    <header className="bg-deepdark flex flex-col items-center py-4 px-6 gap-2">
      <div className="text-6xl text-gold font-bold">Draft Gap</div>
      <div className="text-lg text-silver font-semibold">
        Autonomous League of Legends Esports Betting Simulator.
      </div>
      <div className="text-sm leading-relaxed text-silver/80 font-normal pt-4">
        Using historical data and machine learning, an agent practices betting
        on professional esports matches.
      </div>
      <div className="text-sm leading-relaxed text-silver/80 font-normal">
        The agent continuously adapts to live League of Legends patches to
        refine its predictive accuracy.
      </div>
    </header>
  );
};
