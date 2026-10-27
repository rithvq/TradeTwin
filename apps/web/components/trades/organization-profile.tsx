"use client";
import { useEffect, useState } from "react";
import { Building2, Save, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  tradeRequest,
  TradeApiError,
  type FieldError,
  type Organization,
  type Values,
} from "@/lib/trades";
import { AddressFields, Fields } from "./fields";
import { useTradeContext } from "./trade-context";

const initial = (): Values => ({
  registered_address: { country_code: "IN", timezone: "Asia/Kolkata" },
  registration_position: "NOT_PROVIDED",
});
export function OrganizationProfile() {
  const { org, me, refs, reload, setOrg } = useTradeContext();
  const [profile, setProfile] = useState<Organization | null>(null);
  const [values, setValues] = useState<Values>(initial);
  const [creating, setCreating] = useState(!org);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [registration, setRegistration] = useState<Values>({
    declared_taxpayer_scheme: "UNKNOWN",
    declared_establishment_kind: "UNKNOWN",
  });
  const [location, setLocation] = useState<Values>({
    visibility: "PRIVATE",
    location_type: "OFFICE",
    address: { country_code: "IN", timezone: "Asia/Kolkata" },
  });
  const [memberId, setMemberId] = useState("");
  const [capabilities, setCapabilities] = useState<string[]>([]);
  const [memberStatus, setMemberStatus] = useState("ACTIVE");
  const [members, setMembers] = useState<
    { user_id: string; display_name: string; status: string }[]
  >([]);
  const active = me.memberships.find((item) => item.organization_id === org);
  const canAdmin = active?.capabilities.includes("ORG_ADMIN");
  async function load() {
    if (!org || creating) return;
    try {
      const value = await tradeRequest<Organization>(
        `/organizations/${org}`,
        org,
      );
      setProfile(value);
      const names = [
        "legal_name",
        "trade_name",
        "entity_type",
        "authorised_contact_name",
        "email",
        "mobile_e164",
        "registered_address",
        "registration_position",
        "registration_explanation",
      ];
      setValues(Object.fromEntries(names.map((name) => [name, value[name]])));
      if (canAdmin)
        setMembers(await tradeRequest(`/organizations/${org}/members`, org));
    } catch (problem) {
      setMessage(
        problem instanceof Error ? problem.message : "Profile unavailable",
      );
    }
  }
  useEffect(() => {
    void load();
  }, [org, creating, canAdmin]); // eslint-disable-line react-hooks/exhaustive-deps
  async function run(action: () => Promise<unknown>) {
    setPending(true);
    setMessage("");
    setErrors([]);
    try {
      await action();
      await reload();
      await load();
      setMessage(
        "Saved. Declaration only; no government verification performed.",
      );
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "Save failed");
      if (problem instanceof TradeApiError) setErrors(problem.fields);
    } finally {
      setPending(false);
    }
  }
  async function save() {
    const result = await tradeRequest<Organization>(
      creating ? "/organizations" : `/organizations/${org}`,
      creating ? undefined : org,
      creating ? "POST" : "PATCH",
      values,
      creating ? undefined : profile?.etag,
    );
    setProfile(result);
    setOrg(result.organization_id);
    setCreating(false);
  }
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">
          {creating ? "Create business profile" : "Business profile"}
        </h2>
        <Button
          variant="outline"
          onClick={() => {
            setCreating(true);
            setValues(initial());
            setProfile(null);
          }}
        >
          <Building2 className="size-4" />
          New organisation
        </Button>
      </div>
      <p className="text-sm text-secondary">
        Your user ID: <span className="break-all font-mono">{me.user.id}</span>
      </p>
      {message ? (
        <p
          role="status"
          className="border-l-4 border-accent bg-soft p-3 text-sm"
        >
          {message}
        </p>
      ) : null}
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          void run(save);
        }}
      >
        <Fields
          values={values}
          onChange={setValues}
          errors={errors}
          specs={[
            { path: "legal_name", label: "Legal name", required: true },
            { path: "trade_name", label: "Trading name" },
            {
              path: "entity_type",
              label: "Entity type",
              kind: "select",
              options: [
                "PROPRIETORSHIP",
                "PARTNERSHIP",
                "LLP",
                "COMPANY",
                "TRUST",
                "SOCIETY",
                "OTHER",
              ],
              required: true,
            },
            {
              path: "authorised_contact_name",
              label: "Authorised contact",
              required: true,
              maxLength: 100,
            },
            {
              path: "email",
              label: "Business email",
              kind: "email",
              required: true,
            },
            {
              path: "mobile_e164",
              label: "Mobile (+country code)",
              kind: "phone",
              required: true,
            },
            {
              path: "registration_position",
              label: "Declared registration position",
              kind: "select",
              options: [
                "REGISTERED",
                "UNREGISTERED",
                "EXEMPTION_CLAIMED",
                "NOT_PROVIDED",
              ],
              required: true,
            },
            {
              path: "registration_explanation",
              label: "Registration explanation",
              kind: "textarea",
              maxLength: 1000,
            },
          ]}
        />
        <h3 className="font-semibold">Registered / billing address</h3>
        <AddressFields
          prefix="registered_address"
          values={values}
          onChange={setValues}
          errors={errors}
        />
        <Button type="submit" disabled={pending || (!creating && !canAdmin)}>
          <Save className="size-4" />
          {creating ? "Create organisation" : "Save profile"}
        </Button>
      </form>
      {!creating && profile ? (
        <>
          <section className="space-y-4 border-t border-line pt-5">
            <h3 className="text-lg font-semibold">Declared registrations</h3>
            <p className="text-sm text-secondary">
              Format checks do not verify registration status or ownership.
            </p>
            {profile.registrations.map((item) => (
              <p key={item.id} className="text-sm">
                {item.gstin} | {item.verification_status}
              </p>
            ))}
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                void run(() =>
                  tradeRequest(
                    `/organizations/${org}/registrations`,
                    org,
                    "POST",
                    registration,
                  ),
                );
              }}
            >
              <Fields
                values={registration}
                onChange={setRegistration}
                errors={errors}
                specs={[
                  {
                    path: "gstin",
                    label: "GSTIN",
                    maxLength: 15,
                    required: true,
                  },
                  {
                    path: "state_code",
                    label: "Registration state",
                    kind: "select",
                    options: refs.states,
                    required: true,
                  },
                  {
                    path: "declared_taxpayer_scheme",
                    label: "Declared taxpayer scheme",
                    kind: "select",
                    options: ["REGULAR", "COMPOSITION", "OTHER", "UNKNOWN"],
                  },
                  {
                    path: "declared_establishment_kind",
                    label: "Declared establishment kind",
                    kind: "select",
                    options: ["NORMAL", "SEZ_UNIT", "SEZ_DEVELOPER", "UNKNOWN"],
                  },
                ]}
              />
              <Button
                type="submit"
                variant="outline"
                disabled={!canAdmin || pending}
              >
                Add declaration
              </Button>
            </form>
          </section>
          <section className="space-y-4 border-t border-line pt-5">
            <h3 className="text-lg font-semibold">Operating locations</h3>
            {profile.locations.map((item) => (
              <p key={item.id} className="text-sm">
                {item.label} | {item.visibility}
              </p>
            ))}
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                void run(() =>
                  tradeRequest(
                    `/organizations/${org}/locations`,
                    org,
                    "POST",
                    location,
                  ),
                );
              }}
            >
              <Fields
                values={location}
                onChange={setLocation}
                errors={errors}
                specs={[
                  {
                    path: "label",
                    label: "Location label",
                    maxLength: 100,
                    required: true,
                  },
                  {
                    path: "location_type",
                    label: "Location type",
                    kind: "select",
                    options: [
                      "OFFICE",
                      "WAREHOUSE",
                      "FACTORY",
                      "STORE",
                      "OTHER",
                    ],
                  },
                  {
                    path: "registration_id",
                    label: "Associated registration (optional)",
                    kind: "select",
                    options: Object.fromEntries(
                      profile.registrations.map((item) => [
                        item.id,
                        item.gstin,
                      ]),
                    ),
                  },
                  {
                    path: "visibility",
                    label: "Visibility",
                    kind: "select",
                    options: ["PRIVATE", "TRADING_PROFILE"],
                  },
                ]}
              />
              <AddressFields
                prefix="address"
                values={location}
                onChange={setLocation}
                errors={errors}
              />
              <Button
                variant="outline"
                type="submit"
                disabled={!canAdmin || pending}
              >
                Add location
              </Button>
            </form>
          </section>
          {canAdmin ? (
            <section className="space-y-4 border-t border-line pt-5">
              <h3 className="text-lg font-semibold">
                Membership and capabilities
              </h3>
              <p className="text-sm text-secondary">
                Assign approval permissions explicitly; administrator access
                alone does not grant them.
              </p>
              <ul className="text-sm">
                {members.map((item) => (
                  <li key={item.user_id}>
                    {item.display_name}:{" "}
                    <span className="break-all font-mono">{item.user_id}</span>{" "}
                    ({item.status})
                  </li>
                ))}
              </ul>
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void run(() =>
                    tradeRequest(`/organizations/${org}/members`, org, "POST", {
                      user_id: memberId,
                      status: memberStatus,
                      capabilities,
                    }),
                  );
                }}
              >
                <label className="block text-sm font-medium">
                  Member user ID
                  <input
                    className="mt-1 block w-full rounded border p-2"
                    value={memberId}
                    onChange={(event) => setMemberId(event.target.value)}
                    required
                  />
                </label>
                <Button
                  variant="outline"
                  type="button"
                  onClick={() => {
                    setMemberId(me.user.id);
                    setCapabilities(active?.capabilities ?? []);
                  }}
                >
                  Select my account
                </Button>
                <label className="block text-sm font-medium">
                  Membership status
                  <select
                    className="ml-3 rounded border p-2"
                    value={memberStatus}
                    onChange={(event) => setMemberStatus(event.target.value)}
                  >
                    <option>ACTIVE</option>
                    <option>SUSPENDED</option>
                  </select>
                </label>
                <fieldset className="grid gap-3 sm:grid-cols-2">
                  <legend className="mb-3 text-sm font-semibold">
                    Explicit capability roles
                  </legend>
                  {Object.keys(refs.capability_permissions).map((item) => (
                    <label
                      key={item}
                      className="flex items-center gap-2 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={capabilities.includes(item)}
                        onChange={(event) =>
                          setCapabilities(
                            event.target.checked
                              ? [...capabilities, item]
                              : capabilities.filter((role) => role !== item),
                          )
                        }
                      />
                      {item}
                    </label>
                  ))}
                </fieldset>
                <Button
                  type="submit"
                  disabled={pending || !capabilities.length}
                >
                  <UserPlus className="size-4" />
                  Save member capabilities
                </Button>
              </form>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
