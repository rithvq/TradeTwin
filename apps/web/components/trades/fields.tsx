"use client";
import { useId } from "react";
import {
  getValue,
  localTimeInput,
  setValue,
  type FieldError,
  type Values,
} from "@/lib/trades";
import { useTradeContext } from "./trade-context";

export type FieldSpec = {
  path: string;
  label: string;
  kind?:
    | "text"
    | "textarea"
    | "select"
    | "boolean"
    | "integer"
    | "decimal"
    | "datetime"
    | "date"
    | "time"
    | "email"
    | "phone";
  options?: string[] | Record<string, string>;
  required?: boolean;
  maxLength?: number;
};
export function Fields({
  specs,
  values,
  onChange,
  errors = [],
}: {
  specs: FieldSpec[];
  values: Values;
  onChange: (value: Values) => void;
  errors?: FieldError[];
}) {
  const instance = useId();
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {specs.map((spec) => {
        const value = getValue(values, spec.path);
        const messages = errors.filter(
          (item) =>
            item.path === spec.path || item.path.endsWith(`.${spec.path}`),
        );
        const id = `field-${instance}-${spec.path}`;
        const control =
          "mt-1 block min-h-10 w-full rounded border px-3 py-2 text-sm";
        const change = (next: unknown) =>
          onChange(setValue(values, spec.path, next));
        return (
          <div
            key={spec.path}
            className={spec.kind === "textarea" ? "sm:col-span-2" : ""}
          >
            {spec.kind === "boolean" ? (
              <label
                htmlFor={id}
                className="flex min-h-10 items-center gap-2 text-sm font-medium"
              >
                <input
                  id={id}
                  type="checkbox"
                  checked={value === true}
                  onChange={(event) => change(event.target.checked)}
                />
                {spec.label}
              </label>
            ) : (
              <>
                <label htmlFor={id} className="text-sm font-medium">
                  {spec.label}
                  {spec.required ? " *" : ""}
                </label>
                {spec.kind === "select" ? (
                  <select
                    id={id}
                    className={control}
                    value={String(value ?? "")}
                    onChange={(event) => change(event.target.value || null)}
                    aria-invalid={messages.length > 0}
                    aria-describedby={
                      messages.length ? `${id}-error` : undefined
                    }
                  >
                    <option value="">Not provided</option>
                    {Object.entries(
                      Array.isArray(spec.options)
                        ? Object.fromEntries(
                            spec.options.map((item) => [
                              item,
                              item.replaceAll("_", " "),
                            ]),
                          )
                        : (spec.options ?? {}),
                    ).map(([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ))}
                  </select>
                ) : spec.kind === "textarea" ? (
                  <textarea
                    id={id}
                    className={control}
                    rows={3}
                    maxLength={spec.maxLength ?? 2000}
                    value={String(value ?? "")}
                    onChange={(event) => change(event.target.value || null)}
                    aria-invalid={messages.length > 0}
                    aria-describedby={
                      messages.length ? `${id}-error` : undefined
                    }
                  />
                ) : (
                  <input
                    id={id}
                    className={control}
                    type={
                      spec.kind === "datetime"
                        ? "datetime-local"
                        : spec.kind === "integer"
                          ? "number"
                          : ["time", "date", "email"].includes(spec.kind ?? "")
                            ? spec.kind
                            : "text"
                    }
                    inputMode={
                      spec.kind === "decimal"
                        ? "decimal"
                        : spec.kind === "phone"
                          ? "tel"
                          : undefined
                    }
                    min={spec.kind === "integer" ? 0 : undefined}
                    maxLength={spec.maxLength ?? 200}
                    value={
                      spec.kind === "datetime"
                        ? localTimeInput(value)
                        : String(value ?? "")
                    }
                    onChange={(event) =>
                      change(
                        event.target.value === ""
                          ? null
                          : spec.kind === "integer"
                            ? Number(event.target.value)
                            : spec.kind === "datetime"
                              ? new Date(
                                  `${event.target.value}:00+05:30`,
                                ).toISOString()
                              : event.target.value,
                      )
                    }
                    aria-invalid={messages.length > 0}
                    aria-describedby={
                      messages.length ? `${id}-error` : undefined
                    }
                  />
                )}
              </>
            )}
            {messages.length ? (
              <p
                role="alert"
                id={`${id}-error`}
                className="mt-1 text-xs text-red-800"
              >
                {messages.map((item) => item.message).join(". ")}
              </p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function AddressFields({
  prefix,
  values,
  onChange,
  errors = [],
  operational = false,
}: {
  prefix: string;
  values: Values;
  onChange: (value: Values) => void;
  errors?: FieldError[];
  operational?: boolean;
}) {
  const { refs } = useTradeContext();
  const fields: FieldSpec[] = [
    {
      path: "address_line1",
      label: "Address line 1",
      required: true,
      maxLength: 120,
    },
    { path: "address_line2", label: "Address line 2", maxLength: 120 },
    { path: "locality", label: "Locality", maxLength: 80 },
    { path: "city", label: "City", required: true, maxLength: 80 },
    { path: "district", label: "District", required: true, maxLength: 80 },
    {
      path: "state_code",
      label: "State / Union territory",
      kind: "select",
      options: refs.states,
      required: true,
    },
    { path: "postal_code", label: "PIN code", required: true, maxLength: 6 },
    { path: "timezone", label: "Timezone", required: true },
    {
      path: "contact_name",
      label: "Contact name",
      required: operational,
      maxLength: 100,
    },
    {
      path: "contact_phone_e164",
      label: "Contact phone (+country code)",
      kind: "phone",
      required: operational,
    },
  ];
  return (
    <Fields
      specs={fields.map((field) => ({
        ...field,
        path: `${prefix}.${field.path}`,
      }))}
      values={values}
      onChange={onChange}
      errors={errors}
    />
  );
}
