import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronDown, Download } from "lucide-react"
import { useRef, useState } from "react"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { Button } from "@/components/ui/button"
import { NativeSelect } from "@/components/ui/native-select"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError, type LogUsage, STORAGE_LOGS_URL, api } from "@/lib/api"
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
        clearedActivityMessage(cleared.removed, storage.data?.database.reclaimable_bytes ?? 0),
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["storage"] }),
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
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
      setMessage("The logs were purged.")
      await queryClient.invalidateQueries({ queryKey: ["storage"] })
    },
  })
  const confirmation = clearable.data
    ? clearActivityConfirmation(
        clearable.data.entries,
        days,
        storage.data?.database.reclaimable_bytes ?? 0,
      )
    : clearable.error
      ? countFailedConfirmation(clearable.error.message)
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
  const commands = useStorageCommands()
  const { storage, message, clear, purge } = commands
  const usage = storage.data

  return (
    <section className="settings-section" aria-labelledby="storage-title">
      <div className="section-heading">
        <div>
          <h2 id="storage-title">Storage</h2>
          <p>Activity history and log files kept on this installation.</p>
        </div>
      </div>
      {storage.isPending && <Skeleton className="h-24 w-full" />}
      {storage.error && (
        <div className="inline-error" role="alert">
          Storage usage could not load.
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
          {(clear.error ?? purge.error)?.message}
        </div>
      )}
    </section>
  )
}

function ActivityStorage({ usage, commands }: { usage: StorageUsage; commands: StorageCommands }) {
  const { days, setDays, confirming, setConfirming, setMessage, clear, busy } = commands
  const clearTrigger = useRef<HTMLButtonElement>(null)
  return (
    <>
      <div className="setting-row">
        <div>
          <h3>Database</h3>
          <p>{activitySummary(usage.database)}</p>
        </div>
        <div className="storage-actions">
          <div className="storage-select">
            <NativeSelect
              id="activity-age"
              aria-label="Clear Activity older than"
              value={days}
              disabled={busy}
              onChange={(event) => setDays(Number(event.target.value))}
            >
              {usage.activity_ages.map((age) => (
                <option key={age} value={age}>
                  Older than {age} days
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
            Clear Activity
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
  const { days, confirmation, clearable, clear } = commands
  return (
    <DestructiveConfirmation
      id="clear-activity-confirmation"
      title={`Clear Activity older than ${days} days?`}
      body={confirmation?.body ?? "Counting the entries that would be removed…"}
      cancelLabel="Keep Activity"
      confirmLabel={confirmation?.confirmLabel ?? "Clear Activity"}
      pendingLabel={confirmation?.pendingLabel ?? "Clearing…"}
      pending={clear.isPending || clearable.isRefetching}
      confirmDisabled={!confirmation?.canConfirm}
      onConfirm={() => (clearable.error ? void clearable.refetch() : clear.mutate())}
      onCancel={onCancel}
    />
  )
}

function LogStorage({ logs, commands }: { logs: LogUsage | null; commands: StorageCommands }) {
  const { confirming, setConfirming, setMessage, purge, busy } = commands
  const purgeTrigger = useRef<HTMLButtonElement>(null)
  return (
    <>
      <div className="setting-row">
        <div>
          <h3>Logs</h3>
          <p>{logSummary(logs)}</p>
          {!logs && <LogSetupHelp />}
        </div>
        {logs && (
          <div className="storage-actions">
            <Button variant="outline" asChild>
              <a href={STORAGE_LOGS_URL} download>
                <Download aria-hidden="true" /> Download
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
              Purge logs
            </Button>
          </div>
        )}
      </div>
      {confirming === "logs" && (
        <DestructiveConfirmation
          id="purge-logs-confirmation"
          title="Purge the logs?"
          body="Every log line kept on this installation is deleted. Download them first if you may need them. This cannot be undone."
          cancelLabel="Keep logs"
          confirmLabel="Purge logs"
          pendingLabel="Purging…"
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
  return (
    <details className="inline-help setting-help">
      <summary>
        <span>How to turn it on</span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <div className="inline-help-body">
        <p>
          Log files are kept unless <code>CALENDAR_SYNC_LOG_DIR</code> is set to an empty
          value. Set it to a writable directory, such as <code>/data/logs</code> on the data
          volume, or remove it from <code>.env</code>, then restart the service.
        </p>
        <p>
          If it already names a directory, that directory could not be used:{" "}
          <code>docker compose logs app</code> shows the warning that says why.
        </p>
      </div>
    </details>
  )
}
