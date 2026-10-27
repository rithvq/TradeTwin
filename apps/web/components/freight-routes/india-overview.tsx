import type { IndiaReference, MapRoute } from "@/lib/freight-map";
import { overviewPath, overviewPoint, routeColor } from "@/lib/freight-map";

export function IndiaOverview({
  reference,
  routes,
  selected,
  onOpen,
}: {
  reference: IndiaReference;
  routes: MapRoute[];
  selected: string;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      aria-label="Show routes across India"
      onClick={onOpen}
      className="absolute bottom-8 right-3 z-[450] hidden w-[124px] overflow-hidden rounded-lg border border-line bg-white/95 shadow-sm sm:block"
    >
      <span className="block border-b border-line px-2 py-1.5 text-left text-xs font-semibold text-ink">
        India overview
      </span>
      <svg viewBox="0 0 150 170" aria-hidden="true" className="block w-full">
        {reference.features.map((feature, index) => (
          <path
            key={index}
            d={overviewPath(feature.geometry.coordinates)}
            fill="#e3ecea"
            stroke="#a1b9bd"
            strokeWidth=".55"
            fillRule="evenodd"
          />
        ))}
        {[...routes]
          .sort((a, b) => Number(a.id === selected) - Number(b.id === selected))
          .map((route) => (
            <path
              key={route.id}
              d={route.geometry.coordinates
                .map((p, i) => `${i ? "L" : "M"}${overviewPoint(p).join(",")}`)
                .join(" ")}
              fill="none"
              stroke={routeColor(route, selected)}
              strokeWidth="1.6"
            />
          ))}
        {routes[0] &&
          [
            routes[0].geometry.coordinates[0],
            routes[0].geometry.coordinates.at(-1)!,
          ].map((point, index) => (
            <circle
              key={index}
              cx={overviewPoint(point)[0]}
              cy={overviewPoint(point)[1]}
              r="2.5"
              fill="#08776e"
              stroke="white"
              strokeWidth="1"
            />
          ))}
      </svg>
    </button>
  );
}
