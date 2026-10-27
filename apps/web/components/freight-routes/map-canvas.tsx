"use client";

import { useEffect, useRef, useState } from "react";
import type * as Leaflet from "leaflet";
import {
  INDIA_BOUNDS,
  MAP_ATTRIBUTION,
  OSM_TILES,
  indiaReference,
  routeColor,
  type IndiaReference,
  type MapRoute,
} from "@/lib/freight-map";
import { IndiaOverview } from "./india-overview";

type MapController = {
  sdk: typeof Leaflet;
  map: Leaflet.Map;
  routes: Leaflet.FeatureGroup;
  states: Leaflet.GeoJSON;
};
function text(value: string) {
  const node = document.createElement("span");
  node.textContent = value;
  return node;
}

export function FreightMapCanvas({
  routes,
  selected,
  onSelect,
}: {
  routes: MapRoute[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const initialRoutes = useRef(routes);
  const [controller, setController] = useState<MapController | null>(null);
  const [reference, setReference] = useState<IndiaReference | null>(null);
  const [mapError, setMapError] = useState(false);
  const [tiles, setTiles] = useState("LOADING");
  const fitted = useRef("");
  const [frame, setFrame] = useState<"ROUTES" | "INDIA">("ROUTES");
  const frameRef = useRef(frame);
  useEffect(() => {
    let cancelled = false;
    let map: Leaflet.Map | undefined;
    let resize: ResizeObserver | undefined;
    void import("leaflet")
      .then((sdk) => {
        if (cancelled || !host.current) return;
        map = sdk.map(host.current, {
          scrollWheelZoom: false,
          minZoom: 3,
          maxZoom: 18,
          zoomSnap: 0.5,
          zoomControl: true,
          attributionControl: true,
          zoomAnimation: false,
          markerZoomAnimation: false,
          fadeAnimation: false,
        });
        map.attributionControl.setPrefix(false);
        map.fitBounds(
          sdk.latLngBounds(initialRoutes.current.flatMap((r) => r.positions)),
          {
            padding: [90, 60],
            maxZoom: 11,
            animate: false,
          },
        );
        const current = {
          sdk,
          map,
          routes: sdk.featureGroup().addTo(map),
          states: sdk.geoJSON().addTo(map),
        };
        const layer = sdk.tileLayer(
          process.env.NEXT_PUBLIC_FREIGHT_MAP_TILE_URL || OSM_TILES,
          {
            maxZoom: 19,
            attribution:
              process.env.NEXT_PUBLIC_FREIGHT_MAP_TILE_ATTRIBUTION ||
              MAP_ATTRIBUTION,
            keepBuffer: 1,
          },
        );
        layer.on("tileerror", () => {
          if (!cancelled) setTiles("UNAVAILABLE");
        });
        layer.on("loading", () => {
          if (!cancelled) setTiles("LOADING");
        });
        layer.on("load", () => {
          const images = layer.getContainer()?.querySelectorAll("img");
          if (!cancelled && images?.length)
            setTiles(
              [...images].every(
                (image) => image.complete && image.naturalWidth > 0,
              )
                ? "READY"
                : "UNAVAILABLE",
            );
        });
        layer.addTo(map);
        sdk.control
          .scale({ imperial: false, position: "bottomleft" })
          .addTo(map);
        if (typeof ResizeObserver !== "undefined") {
          resize = new ResizeObserver(() => {
            current.map.invalidateSize({ pan: false });
            const bounds = current.routes.getBounds();
            if (bounds.isValid())
              current.map.fitBounds(
                frameRef.current === "INDIA" ? INDIA_BOUNDS : bounds,
                {
                  padding: frameRef.current === "INDIA" ? [12, 12] : [90, 60],
                  maxZoom: frameRef.current === "INDIA" ? 5 : 11,
                  animate: false,
                },
              );
          });
          resize.observe(host.current);
        }
        setController(current);
        void indiaReference()
          .then((data) => {
            if (!cancelled) setReference(data);
          })
          .catch(() => {});
      })
      .catch(() => {
        if (!cancelled) setMapError(true);
      });
    return () => {
      cancelled = true;
      resize?.disconnect();
      map?.remove();
    };
  }, []);
  useEffect(() => {
    if (!controller) return;
    const { sdk, map, routes: layers } = controller;
    layers.clearLayers();
    const ordered = [...routes].sort(
      (a, b) => Number(a.id === selected) - Number(b.id === selected),
    );
    for (const route of ordered) {
      const active = route.id === selected;
      const schematic = route.geometry_kind !== "ROAD_GEOMETRY";
      const label = `Route ${routes.findIndex((r) => r.id === route.id) + 1}${route.feasibility === "EXCLUDED" ? " · excluded" : ""}`;
      if (active)
        sdk
          .polyline(route.positions, {
            color: "white",
            weight: 8,
            opacity: 0.9,
            interactive: false,
          })
          .addTo(layers);
      sdk
        .polyline(route.positions, {
          color: routeColor(route, selected),
          weight: active ? 4.5 : 3,
          opacity: active ? 1 : 0.75,
          dashArray: schematic ? "8 7" : active ? undefined : "5 6",
          lineCap: "round",
        })
        .bindTooltip(
          text(
            `${label} · ${schematic ? "simulated connection" : "recorded road route"}`,
          ),
          { sticky: true },
        )
        .on("click", () => onSelect(route.id))
        .addTo(layers);
      if (schematic)
        for (const point of route.positions.slice(1, -1))
          sdk
            .circleMarker(point, {
              radius: 3.5,
              color: routeColor(route, selected),
              fillColor: "white",
              fillOpacity: 1,
              weight: 1.5,
            })
            .addTo(layers);
    }
    const active = routes.find((r) => r.id === selected) ?? routes[0];
    if (active)
      for (const [i, point] of [
        active.positions[0],
        active.positions.at(-1)!,
      ].entries()) {
        const state = i
          ? active.corridor.state_names.at(-1)
          : active.corridor.state_names[0];
        const label = `${i ? "Delivery" : "Pickup"}${state ? ` · ${state}` : ""}`;
        sdk
          .circleMarker(point, {
            radius: 8,
            color: "white",
            weight: 3,
            fillColor: i ? "#173642" : "#08776e",
            fillOpacity: 1,
          })
          .bindTooltip(text(label), {
            permanent: true,
            direction: frame === "INDIA" ? (i ? "right" : "left") : "top",
            offset: frame === "INDIA" ? [0, 0] : [0, -11],
            className: "tt-map-pin",
          })
          .bindPopup(
            text(
              `${label}: ${point[0].toFixed(5)}° N, ${point[1].toFixed(5)}° E`,
            ),
          )
          .addTo(layers);
      }
    const signature =
      routes
        .map(
          (r) =>
            r.id + ":" + r.positions.length + ":" + r.positions[0].join(","),
        )
        .join("|") +
      ":" +
      layers.getBounds().toBBoxString();
    if (layers.getBounds().isValid() && fitted.current !== signature) {
      map.fitBounds(layers.getBounds(), {
        padding: [90, 60],
        maxZoom: 11,
        animate: false,
      });
      fitted.current = signature;
      frameRef.current = "ROUTES";
      setFrame("ROUTES");
    }
  }, [controller, routes, selected, onSelect, frame]);
  useEffect(() => {
    if (!controller || !reference) return;
    controller.states.clearLayers();
    const states = new Set(
      routes
        .flatMap((r) => r.corridor.state_names)
        .map((name) => name.toLowerCase()),
    );
    controller.sdk
      .geoJSON(reference, {
        style: (feature) => ({
          color: "#78989c",
          weight: 1,
          opacity: 0.65,
          fillColor: states.has(String(feature?.properties?.name).toLowerCase())
            ? "#d4e8e0"
            : "#e7eeea",
          fillOpacity: tiles === "UNAVAILABLE" ? 0.8 : 0.05,
        }),
        onEachFeature: (feature, layer) => {
          layer.bindTooltip(
            text(String(feature.properties.name) + " · reference boundary"),
          );
        },
      })
      .addTo(controller.states);
    controller.states.bringToBack();
  }, [controller, reference, routes, tiles]);
  function fit(view: "ROUTES" | "INDIA") {
    if (!controller) return;
    controller.map.fitBounds(
      view === "INDIA" ? INDIA_BOUNDS : controller.routes.getBounds(),
      {
        padding: view === "INDIA" ? [12, 12] : [90, 60],
        maxZoom: view === "INDIA" ? 5 : 11,
        animate: false,
      },
    );
    frameRef.current = view;
    setFrame(view);
  }
  return (
    <div className="relative isolate bg-[#e8f0f2]">
      <div
        ref={host}
        className="tt-freight-map h-[380px] w-full sm:h-[480px]"
        aria-label="Interactive India road map"
      />
      <div
        className="absolute right-3 top-3 z-[450] flex rounded-lg border border-line bg-white p-1 shadow-sm"
        aria-label="Map extent"
      >
        <button
          type="button"
          onClick={() => fit("ROUTES")}
          aria-pressed={frame === "ROUTES"}
          className={`rounded-md px-3 py-2 text-xs font-semibold ${frame === "ROUTES" ? "bg-soft text-ink" : "text-secondary"}`}
        >
          Fit routes
        </button>
        <button
          type="button"
          onClick={() => fit("INDIA")}
          aria-pressed={frame === "INDIA"}
          className={`rounded-md px-3 py-2 text-xs font-semibold ${frame === "INDIA" ? "bg-soft text-ink" : "text-secondary"}`}
        >
          All India
        </button>
      </div>
      {reference && (
        <IndiaOverview
          reference={reference}
          routes={routes}
          selected={selected}
          onOpen={() => fit("INDIA")}
        />
      )}
      {mapError && (
        <p
          role="status"
          className="absolute bottom-12 left-3 z-[450] rounded bg-white p-3 text-sm"
        >
          Map could not load. Reload to retry.
        </p>
      )}
      {!mapError && tiles === "UNAVAILABLE" && (
        <p
          role="status"
          className="absolute bottom-12 left-3 z-[450] max-w-[220px] rounded bg-white/95 p-2 text-xs"
        >
          {reference
            ? "Road tiles unavailable. Showing the India state reference."
            : "Road tiles unavailable. Check your connection."}
        </p>
      )}
    </div>
  );
}
