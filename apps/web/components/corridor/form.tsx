"use client";
import { useState } from "react";
import { Check } from "lucide-react";
import { Fields, type FieldSpec } from "@/components/trades/fields";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationalMutation } from "@/hooks/use-operations";
import { Button } from "@/components/ui/button";
import type { Values } from "@/lib/trades";

export function CorridorForm({
  name,
  path,
  initial,
  specs,
  reload,
  transform = (value) => value,
  etag,
  saved,
}: {
  name: string;
  path: string;
  initial: Values;
  specs: FieldSpec[];
  reload: () => Promise<void>;
  transform?: (value: Values) => Values;
  etag?: string;
  saved?: (value: Values) => void;
}) {
  const { org } = useTradeContext();
  const mutation = useOperationalMutation(org, reload);
  const [values, setValues] = useState(initial);
  return (
    <form
      className="space-y-3"
      onSubmit={async (event) => {
        event.preventDefault();
        const result = await mutation.run<Values>(
          path,
          transform(values),
          etag,
        );
        if (result) saved?.(result);
      }}
    >
      <Fields
        values={values}
        onChange={setValues}
        specs={specs}
        errors={mutation.error?.fields}
      />
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
      {mutation.saved && <p role="status">{mutation.saved}</p>}
      <Button disabled={mutation.pending}>
        <Check className="size-4" />
        {name}
      </Button>
    </form>
  );
}
