"use client";

import { Pencil, Send } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { cn } from "@/components/ui/cn";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { QuestionOut } from "@/lib/api/types";
import { questionPoller } from "@/lib/resources";
import { usePoller } from "@/lib/store/poller";
import { toast } from "@/lib/toast";

const MAX_ANSWER = 140;

/**
 * One light music question a day. The other member's answer shows once you
 * have answered too; nobody is told who has answered.
 */
export function DailyQuestion({ myName, partnerName }: { myName: string; partnerName: string | null }) {
  const polled = usePoller(questionPoller);
  // What the last save returned, until a fresh poll supersedes it.
  const [saved, setSaved] = useState<{ result: QuestionOut; after: QuestionOut | undefined } | null>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const inputId = useId();

  const data = saved && saved.after === polled.data ? saved.result : polled.data;
  if (!data) return null;
  const answering = data.my_answer === null || editing;

  async function save(event: FormEvent) {
    event.preventDefault();
    const answer = text.trim();
    if (!answer) return;
    setBusy(true);
    try {
      setSaved({ result: await api.answerQuestion(answer), after: polled.data });
      setEditing(false);
      setText("");
    } catch (error) {
      if (!(error instanceof ApiError && error.isUnauthenticated)) {
        toast(error instanceof ApiError && error.status === 422 ? error.message : "Couldn't save it. Please try again.", "error");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card aria-labelledby="question-heading">
      <p className="text-sm font-semibold text-muted">Today</p>
      <CardTitle id="question-heading" className="mt-1">
        {data.question}
      </CardTitle>
      {answering ? (
        <form onSubmit={(event) => void save(event)} className="mt-4 flex items-center gap-2">
          <label htmlFor={inputId} className="sr-only">
            Your answer
          </label>
          <input
            id={inputId}
            value={text}
            onChange={(event) => setText(event.target.value)}
            maxLength={MAX_ANSWER}
            autoComplete="off"
            enterKeyHint="send"
            className={cn(
              "block min-h-12 min-w-0 flex-1 rounded-2xl border border-line-strong/70 bg-surface px-4 text-base text-ink",
              "transition-colors focus:border-accent focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-2",
            )}
          />
          <Button
            type="submit"
            className="size-12 shrink-0 px-0"
            aria-label="Save answer"
            loading={busy}
            disabled={!text.trim()}
            icon={<Send aria-hidden className="size-4" />}
          />
        </form>
      ) : (
        <ul className="mt-4 space-y-3">
          <Answer
            name={myName}
            text={data.my_answer ?? ""}
            mine
            onEdit={() => {
              setText(data.my_answer ?? "");
              setEditing(true);
            }}
          />
          {data.partner_answer && partnerName ? <Answer name={partnerName} text={data.partner_answer} /> : null}
        </ul>
      )}
    </Card>
  );
}

function Answer({
  name,
  text,
  mine = false,
  onEdit,
}: {
  name: string;
  text: string;
  mine?: boolean;
  onEdit?: () => void;
}) {
  return (
    <li className="flex items-center gap-3">
      <span
        aria-hidden="true"
        className={cn(
          "inline-flex size-9 shrink-0 items-center justify-center rounded-full font-display text-lg font-semibold",
          mine ? "bg-sage-soft text-sage-ink" : "bg-accent-soft text-accent-text",
        )}
      >
        {name.slice(0, 1).toUpperCase()}
      </span>
      <p className="min-w-0 flex-1 break-words text-[0.97rem] text-ink">
        <span className="sr-only">{name}: </span>
        {text}
      </p>
      {mine && onEdit ? (
        <Button
          variant="ghost"
          size="sm"
          className="size-11 shrink-0 px-0"
          aria-label="Edit your answer"
          onClick={onEdit}
          icon={<Pencil aria-hidden className="size-4" />}
        />
      ) : null}
    </li>
  );
}
