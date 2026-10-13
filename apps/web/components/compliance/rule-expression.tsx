"use client";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export type Expression = {
  op: string;
  path?: string;
  type?: string;
  value?: string | number | boolean | null | string[];
  args?: Expression[];
};
const empty = (): Expression => ({ op: "literal", value: true });
export function RuleExpression({
  value,
  onChange,
  depth = 0,
}: {
  value: Expression;
  onChange: (next: Expression) => void;
  depth?: number;
}) {
  const ops = [
    "literal",
    "field",
    "and",
    "or",
    "not",
    "required",
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "contains_all",
    "set_equal",
  ];
  function operator(op: string) {
    onChange(
      op === "literal"
        ? empty()
        : op === "field"
          ? { op, path: "", type: "value" }
          : {
              op,
              type: "value",
              args: Array.from(
                { length: ["not", "required"].includes(op) ? 1 : 2 },
                empty,
              ),
            },
    );
  }
  return (
    <fieldset className="min-w-0 space-y-2 border-l-2 border-line pl-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="rounded border p-2 text-sm"
          aria-label="Rule operator"
          value={value.op}
          onChange={(e) => operator(e.target.value)}
        >
          {ops.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
        {value.op === "field" && (
          <input
            className="min-w-0 flex-1 rounded border p-2 text-sm"
            aria-label="Input field path"
            value={value.path ?? ""}
            onChange={(e) => onChange({ ...value, path: e.target.value })}
          />
        )}
        {value.op !== "literal" && (
          <select
            className="rounded border p-2 text-sm"
            aria-label="Rule value type"
            value={value.type ?? "value"}
            onChange={(e) => onChange({ ...value, type: e.target.value })}
          >
            {["value", "boolean", "money", "decimal", "date", "timestamp"].map(
              (t) => (
                <option key={t}>{t}</option>
              ),
            )}
          </select>
        )}
        {value.op === "literal" && (
          <>
            <select
              aria-label="Literal kind"
              className="rounded border p-2 text-sm"
              value={
                value.value === null
                  ? "unknown"
                  : typeof value.value === "boolean"
                    ? "boolean"
                    : Array.isArray(value.value)
                      ? "list"
                      : "text"
              }
              onChange={(e) =>
                onChange({
                  op: "literal",
                  value:
                    e.target.value === "boolean"
                      ? true
                      : e.target.value === "unknown"
                        ? null
                        : e.target.value === "list"
                          ? []
                          : "",
                })
              }
            >
              <option value="text">Text / decimal string</option>
              <option value="boolean">Boolean</option>
              <option value="unknown">Unknown</option>
              <option value="list">Value list</option>
            </select>
            {typeof value.value === "boolean" ? (
              <select
                aria-label="Boolean value"
                className="rounded border p-2 text-sm"
                value={String(value.value)}
                onChange={(e) =>
                  onChange({ op: "literal", value: e.target.value === "true" })
                }
              >
                <option value="true">True</option>
                <option value="false">False</option>
              </select>
            ) : (
              value.value !== null && (
                <input
                  aria-label="Literal value"
                  className="min-w-0 flex-1 rounded border p-2 text-sm"
                  value={
                    Array.isArray(value.value)
                      ? value.value.join(", ")
                      : String(value.value ?? "")
                  }
                  onChange={(e) =>
                    onChange({
                      op: "literal",
                      value: Array.isArray(value.value)
                        ? e.target.value
                            .split(",")
                            .map((s) => s.trim())
                            .filter(Boolean)
                        : e.target.value,
                    })
                  }
                />
              )
            )}
          </>
        )}
      </div>
      {depth < 12 &&
        value.args?.map((argument, index) => (
          <div key={index} className="flex min-w-0 items-start gap-2">
            <div className="min-w-0 flex-1">
              <RuleExpression
                depth={depth + 1}
                value={argument}
                onChange={(next) =>
                  onChange({
                    ...value,
                    args: value.args?.map((a, i) => (i === index ? next : a)),
                  })
                }
              />
            </div>
            {["and", "or"].includes(value.op) && value.args!.length > 1 && (
              <Button
                size="icon"
                variant="outline"
                title="Remove condition"
                aria-label="Remove condition"
                onClick={() =>
                  onChange({
                    ...value,
                    args: value.args?.filter((_, i) => i !== index),
                  })
                }
              >
                <Trash2 className="size-4" />
              </Button>
            )}
          </div>
        ))}
      {["and", "or"].includes(value.op) && (value.args?.length ?? 0) < 40 && (
        <Button
          variant="outline"
          onClick={() =>
            onChange({ ...value, args: [...(value.args ?? []), empty()] })
          }
        >
          <Plus className="size-4" />
          Add condition
        </Button>
      )}
    </fieldset>
  );
}
