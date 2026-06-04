import { useRef } from "react";
import {
  Layout as FlexLayout,
  Model,
  type IJsonModel,
  type TabNode,
} from "flexlayout-react";
import "flexlayout-react/style/light.css";

import { OptionsPanel } from "../panels/OptionsPanel";
import { PartInspectorPanel } from "../panels/PartInspectorPanel";
import { PartsPanel } from "../panels/PartsPanel";
import { StepInspectorPanel } from "../panels/StepInspectorPanel";
import { StepsPanel } from "../panels/StepsPanel";
import { StepView } from "../viewport/StepView";
import { Viewport } from "../viewport/Viewport";
import { LAYOUT_KEY } from "./layoutStorage";

// Every panel the default layout provides. A persisted layout missing any of
// these (e.g. saved before a panel was added) is discarded in favor of the
// default, so new panels like "Step view" always show up.
const REQUIRED_COMPONENTS = [
  "steps",
  "viewport",
  "stepview",
  "step",
  "part",
  "parts",
  "options",
];

const DEFAULT_LAYOUT: IJsonModel = {
  global: {
    tabEnableClose: false,
    tabEnableRename: false,
    tabSetEnableMaximize: true,
    splitterSize: 6,
  },
  borders: [],
  layout: {
    type: "row",
    children: [
      // Left column: steps list with the step inspector beneath it.
      {
        type: "row",
        weight: 22,
        children: [
          {
            type: "tabset",
            weight: 42,
            children: [{ type: "tab", name: "Steps", component: "steps" }],
          },
          {
            type: "tabset",
            weight: 58,
            children: [{ type: "tab", name: "Step inspector", component: "step" }],
          },
        ],
      },
      // Center: the 3D viewport.
      {
        type: "tabset",
        weight: 50,
        children: [{ type: "tab", name: "Viewport", component: "viewport" }],
      },
      // Right column: a small persistent step-view preview in the top-right
      // corner, then the parts list (with Options as a hidden tab), then the
      // part inspector beneath it.
      {
        type: "row",
        weight: 28,
        children: [
          {
            type: "tabset",
            weight: 28,
            children: [{ type: "tab", name: "Step view", component: "stepview" }],
          },
          {
            type: "tabset",
            weight: 38,
            selected: 0,
            children: [
              { type: "tab", name: "Parts", component: "parts" },
              { type: "tab", name: "Options", component: "options" },
            ],
          },
          {
            type: "tabset",
            weight: 34,
            children: [{ type: "tab", name: "Part inspector", component: "part" }],
          },
        ],
      },
    ],
  },
};

function loadModel(): Model {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (raw && REQUIRED_COMPONENTS.every((c) => raw.includes(`"${c}"`))) {
      return Model.fromJson(JSON.parse(raw));
    }
  } catch {
    // Ignore corrupt saved layout and fall back to the default.
  }
  return Model.fromJson(DEFAULT_LAYOUT);
}

/** IDE-style dockable panel layout (caplin/FlexLayout). */
export function Layout() {
  const modelRef = useRef<Model>();
  if (!modelRef.current) modelRef.current = loadModel();

  const factory = (node: TabNode) => {
    switch (node.getComponent()) {
      case "steps":
        return <StepsPanel />;
      case "viewport":
        return <Viewport />;
      case "stepview":
        return <StepView />;
      case "step":
        return <StepInspectorPanel />;
      case "part":
        return <PartInspectorPanel />;
      case "parts":
        return <PartsPanel />;
      case "options":
        return <OptionsPanel />;
      default:
        return null;
    }
  };

  return (
    <div className="layout-host">
      <FlexLayout
        model={modelRef.current}
        factory={factory}
        onModelChange={(model) => {
          try {
            localStorage.setItem(LAYOUT_KEY, JSON.stringify(model.toJson()));
          } catch {
            // Best-effort layout persistence.
          }
        }}
      />
    </div>
  );
}
