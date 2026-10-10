import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronDown, Download } from "lucide-react"
import { useRef, useState } from "react"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { Button } from "@/components/ui/button"
import { NativeSelect } from "@/components/ui/native-select"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { codeTag, rich } from "@/i18n/rich"
import { ApiError, type LogUsage, STORAGE_LOGS_URL, api } from "@/lib/api"
import { OWN_OVERVIEW_QUERY } from "@/lib/operator-overview"
import {
  activitySummary,
  canClearActivity,
  clearActivityConfirmation,
  clearedActivityMessage,
  countFailedConfirmation,
  logSummary,
} from "@/lib/storage"

/** The storage usage, the open confirmation, and the commands that clear Activity or purge logs. */
function useStorageCommands() {
  const i18n = useI18n()
  const queryClient = useQueryClient()
  const storage = useQuery({ queryKey: ["storage"], queryFn: api.storage })
  const [days, setDays] = useState(90)
  const [confirming, setConfirming] = useState<"activity" | "logs" | null>(null)
  const [message, setMessage] = useState("")
  const clearable = useQuery({
    queryKey: ["storage", "clearable", days],
    queryFn: () => api.clearableActivity(days),
    enabled: confirming === "activity",
  })
  const clear = useMutation({
    mutationFn: () => api.clearActivity(days),
    onSuccess: async (cleared) => {
      setConfirming(null)
      setMessage(
        clearedActivityMessage(i18n, cleared.removed, storage.data?.database.reclaimable_bytes ?? 0),
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["storage"] }),
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
        queryClient.invalidateQueries({ queryKey: OWN_OVERVIEW_QUERY }),
      ])
    },
    onError: async (error) => {
      // A 409 means the clear deleted entries but could not reclaim the space while a rule
      // was synchronizing. Close the confirmation, keep the server's message in the alert, and
      // refresh the usage, so the row offers to reclaim the space that is left.
      if (error instanceof ApiError && error.status === 409) {
        setConfirming(null)
        await queryClient.invalidateQueries({ queryKey: ["storage"] })
      }
    },
  })
  const purge = useMutation({
    mutationFn: api.purgeLogs,
    onSuccess: async () => {
      setConfirming(null)
      setMessage(i18n.t("settings.storage.logs.purged"))
      await queryClient.invalidateQueries({ queryKey: ["storage"] })
    },
  })
  const confirmation = clearable.data
    ? clearActivityConfirmation(
        i18n,
        clearable.data.entries,
        days,
        storage.data?.database.reclaimable_bytes ?? 0,
      )
    : clearable.error
      ? countFailedConfirmation(i18n, clearable.error)
      : null
  return {
    storage,
    days,
    setDays,
    confirming,
    setConfirming,
    message,
    setMessage,
    clearable,
    clear,
    purge,
    confirmation,
    busy: clear.isPending || purge.isPending,
  }
}

type StorageCommands = ReturnType<typeof useStorageCommands>
type StorageUsage = NonNullable<StorageCommands["storage"]["data"]>

export function StorageSection() {
  const i18n = useI18n()
  const { t } = i18n
  const commands = useStorageCommands()
  const { storage, message, clear, purge } = commands
  const usage = storage.data

  return (
    <section className="settings-section" aria-labelledby="storage-title">
      <div className="section-heading">
        <div>
          <h2 id="storage-title">{t("settings.storage.title")}</h2>
          <p>{t("settings.storage.intro")}</p>
        </div>
      </div>
      {storage.isPending && <Skeleton className="h-24 w-full" />}
      {storage.error && (
        <div className="inline-error" role="alert">
          {t("settings.storage.loadError")}
        </div>
      )}
      {usage && (
        <div className="settings-list">
          <ActivityStorage usage={usage} commands={commands} />
          <LogStorage logs={usage.logs} commands={commands} />
        </div>
      )}
      {message && <p role="status">{message}</p>}
      {(clear.error ?? purge.error) && (
        <div className="inline-error" role="alert">
          {apiErrorMessage(i18n, clear.error ?? purge.error)}
        </div>
      )}
    </section>
  )
}

function ActivityStorage({ usage, commands }: { usage: StorageUsage; commands: StorageCommands }) {
  const i18n = useI18n()
  const { t } = i18n
  const { days, setDays, confirming, setConfirming, setMessage, clear, busy } = commands
  const clearTrigger = useRef<HTMLButtonElement>(null)
  return (
    <>
      <div className="setting-row">
        <div>
          <h3>{t("settings.storage.database")}</h3>
          <p>{activitySummary(i18n, usage.database)}</p>
        </div>
        <div className="storage-actions">
          <div className="storage-select">
            <NativeSelect
              id="activity-age"
              aria-label={t("settings.storage.age.label")}
              value={days}
              disabled={busy}
              onChange={(event) => setDays(Number(event.target.value))}
            >
              {usage.activity_ages.map((age) => (
                <option key={age} value={age}>
                  {t("settings.storage.age.option", { count: age })}
                </option>
              ))}
            </NativeSelect>
          </div>
          <Button
            ref={clearTrigger}
            type="button"
            variant="outline"
            disabled={busy || !canClearActivity(usage.database)}
            aria-expanded={confirming === "activity"}
            aria-controls="clear-activity-confirmation"
            onClick={() => {
              clear.reset()
              setMessage("")
              setConfirming("activity")
            }}
          >
            {t("settings.storage.clear.action")}
          </Button>
        </div>
      </div>
      {confirming === "activity" && (
        <ClearActivityConfirmation
          commands={commands}
          onCancel={() => {
            setConfirming(null)
            clearTrigger.current?.focus()
          }}
        />
      )}
    </>
  )
}

function ClearActivityConfirmation({
  commands,
  onCancel,
}: {
  commands: StorageCommands
  onCancel: () => void
}) {
  const { t } = useI18n()
  const { days, confirmation, clearable, clear } = commands
  return (
    <DestructiveConfirmation
      id="clear-activity-confirmation"
      title={t("settings.storage.clear.title", { count: days })}
      body={confirmation?.body ?? t("settings.storage.clear.counting")}
      cancelLabel={t("settings.storage.clear.keep")}
      confirmLabel={confirmation?.confirmLabel ?? t("settings.storage.clear.action")}
      pendingLabel={confirmation?.pendingLabel ?? t("settings.storage.clear.pending")}
      pending={clear.isPending || clearable.isRefetching}
      confirmDisabled={!confirmation?.canConfirm}
      onConfirm={() => (clearable.error ? void clearable.refetch() : clear.mutate())}
      onCancel={onCancel}
    />
  )
}

function LogStorage({ logs, commands }: { logs: LogUsage | null; commands: StorageCommands }) {
  const i18n = useI18n()
  const { t } = i18n
  const { confirming, setConfirming, setMessage, purge, busy } = commands
  const purgeTrigger = useRef<HTMLButtonElement>(null)
  return (
    <>
      <div className="setting-row">
        <div>
          <h3>{t("settings.storage.logs.title")}</h3>
          <p>{logSummary(i18n, logs)}</p>
          {!logs && <LogSetupHelp />}
        </div>
        {logs && (
          <div className="storage-actions">
            <Button variant="outline" asChild>
              <a href={STORAGE_LOGS_URL} download>
                <Download aria-hidden="true" /> {t("settings.storage.logs.download")}
              </a>
            </Button>
            <Button
              ref={purgeTrigger}
              type="button"
              variant="outline"
              disabled={busy || logs.files === 0}
              aria-expanded={confirming === "logs"}
              aria-controls="purge-logs-confirmation"
              onClick={() => {
                purge.reset()
                setMessage("")
                setConfirming("logs")
              }}
            >
              {t("settings.storage.logs.purge")}
            </Button>
          </div>
        )}
      </div>
      {confirming === "logs" && (
        <DestructiveConfirmation
          id="purge-logs-confirmation"
          title={t("settings.storage.logs.purgeTitle")}
          body={t("settings.storage.logs.purgeBody")}
          cancelLabel={t("settings.storage.logs.keep")}
          confirmLabel={t("settings.storage.logs.purge")}
          pendingLabel={t("settings.storage.logs.purging")}
          pending={purge.isPending}
          onConfirm={() => purge.mutate()}
          onCancel={() => {
            setConfirming(null)
            purgeTrigger.current?.focus()
          }}
        />
      )}
    </>
  )
}

function LogSetupHelp() {
  const { t } = useI18n()
  return (
    <details className="inline-help setting-help">
      <summary>
        <span>{t("settings.storage.logs.help.summary")}</span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <div className="inline-help-body">
        <p>{rich(t("settings.storage.logs.help.body"), { code: codeTag })}</p>
        <p>{rich(t("settings.storage.logs.help.unusable"), { code: codeTag })}</p>
      </div>
    </details>
  )
}
