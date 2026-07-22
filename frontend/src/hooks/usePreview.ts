import { useCallback, useEffect, useState } from "react";

import type { ApiClient } from "../api";
import type { Artifact } from "../types";

/**
 * Loads preview slide blobs into object URLs for the selected job, keeps a
 * selected page, and wires fullscreen + arrow-key navigation. Revokes every
 * object URL on cleanup to avoid leaks.
 */
export function usePreview(
  client: ApiClient | null,
  selectedId: string | null,
  previewArtifacts: Artifact[],
  previewPaneRef: React.RefObject<HTMLElement | null>,
  onError: (message: string) => void,
) {
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({});
  const [selectedPreviewId, setSelectedPreviewId] = useState<string | null>(
    null,
  );
  const [fullscreen, setFullscreen] = useState(false);

  const previewKey = previewArtifacts
    .map((item) => `${item.id}:${item.sha256}`)
    .join(",");

  useEffect(() => {
    if (!client || !selectedId || previewArtifacts.length === 0) {
      setPreviewUrls({});
      setSelectedPreviewId(null);
      return;
    }
    let active = true;
    const objectUrls: string[] = [];
    Promise.all(
      previewArtifacts.map(async (artifact) => {
        const blob = await client.artifactBlob(selectedId, artifact.id, true);
        const url = URL.createObjectURL(blob);
        objectUrls.push(url);
        return [artifact.id, url] as const;
      }),
    )
      .then((entries) => {
        if (!active) return;
        setPreviewUrls(Object.fromEntries(entries));
        setSelectedPreviewId((current) =>
          current && entries.some(([id]) => id === current)
            ? current
            : entries[0]?.[0] || null,
        );
      })
      .catch((reason: unknown) => {
        if (active)
          onError(reason instanceof Error ? reason.message : "预览读取失败");
      });
    return () => {
      active = false;
      objectUrls.forEach((url) => URL.revokeObjectURL(url));
    };
    // previewKey captures the artifact identity set without re-running per render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, selectedId, previewKey, onError]);

  const selectedIndex = previewArtifacts.findIndex(
    (artifact) => artifact.id === selectedPreviewId,
  );

  const goTo = useCallback(
    (index: number) => {
      const target = previewArtifacts[index];
      if (target) setSelectedPreviewId(target.id);
    },
    [previewArtifacts],
  );

  useEffect(() => {
    const handleChange = () =>
      setFullscreen(document.fullscreenElement === previewPaneRef.current);
    document.addEventListener("fullscreenchange", handleChange);
    return () => document.removeEventListener("fullscreenchange", handleChange);
  }, [previewPaneRef]);

  useEffect(() => {
    if (!fullscreen) return;
    const handleKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "ArrowLeft" && selectedIndex > 0)
        goTo(selectedIndex - 1);
      if (
        event.key === "ArrowRight" &&
        selectedIndex >= 0 &&
        selectedIndex < previewArtifacts.length - 1
      )
        goTo(selectedIndex + 1);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [fullscreen, selectedIndex, previewArtifacts.length, goTo]);

  const toggleFullscreen = useCallback(async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await previewPaneRef.current?.requestFullscreen();
      }
    } catch {
      onError("浏览器未能进入全屏预览");
    }
  }, [previewPaneRef, onError]);

  return {
    previewUrls,
    selectedPreviewId,
    setSelectedPreviewId,
    selectedIndex,
    goTo,
    fullscreen,
    toggleFullscreen,
  };
}
