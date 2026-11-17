import { useEffect, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useLocale } from "@vibe-sorcery/i18n";
import { PageShell } from "../PageShell";
import { vibeApi } from "../../services/api";
import { getBundledLegalDocument } from "../../data/legal-documents";
import { useLegalMeta, type LegalMeta } from "../../hooks/useLegalMeta";
import "./LegalDocumentView.scss";

function applyLiveContacts(content: string, meta: LegalMeta | null) {
  const email = (meta?.contact_email || "").trim();
  const phone = (meta?.contact_phone || "").trim();
  let out = content;
  if (email && email !== "privacy@vibe-sorcery.com") {
    out = out.split("privacy@vibe-sorcery.com").join(email);
  }
  if (phone && phone !== "400-000-0000") {
    out = out.split("400-000-0000").join(phone);
  } else {
    out = out.replace(/[-－] ?(?:客服)?电话：400-000-0000\r?\n?/g, "");
    out = out.split("400-000-0000").join("");
  }
  return out;
}

type Props = {
  slug: string;
  title?: string;
};

function stripMarkdownTables(text: string, cellJoin = "："): string {
  return text.replace(/^\|.+\|\s*\n\|[-| :]+\|\s*\n(?:\|.+\|\s*\n?)+/gm, (block) => {
    const rows = block.trim().split("\n").filter((line) => !/^\|[-| :]+\|$/.test(line.trim()));
    return rows
      .map((row) =>
        row
          .split("|")
          .map((cell) => cell.trim())
          .filter(Boolean)
          .join(cellJoin),
      )
      .join("\n\n");
  });
}

function formatParagraphs(content: string, locale?: string): string[] {
  const cellJoin = locale === "en" ? ": " : "：";
  const plain = stripMarkdownTables(content.replace(/^#+\s+/gm, "").replace(/\*\*(.+?)\*\*/g, "$1"), cellJoin);
  return plain.split(/\n\n+/).filter(Boolean);
}

export function LegalDocumentView({ slug, title }: Props) {
  const { copy, locale } = useLocale();
  const legalMeta = useLegalMeta();
  const [content, setContent] = useState("");
  const [docTitle, setDocTitle] = useState(title || "");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const isWeapp = process.env.TARO_ENV === "weapp";
  const skipBundled = locale === "en";

  useEffect(() => {
    let cancelled = false;
    setLoadError(false);
    setContent("");
    if (title) setDocTitle(title);
    setLoading(true);

    const bundled = skipBundled ? undefined : getBundledLegalDocument(slug);
    if (bundled) {
      setContent(bundled.content);
      setDocTitle(bundled.title);
      setLoading(false);
    }

    const weappZhOffline = isWeapp && !skipBundled;
    if (weappZhOffline) {
      if (!bundled) {
        setLoadError(true);
        setLoading(false);
      }
      return;
    }

    vibeApi
      .getLegalDocument(slug, locale)
      .then((doc) => {
        if (cancelled) return;
        if (locale === "en" && doc.locale !== "en") {
          setLoadError(true);
          setContent("");
          return;
        }
        setContent(doc.content);
        setDocTitle(doc.title);
        setLoadError(false);
      })
      .catch(() => {
        if (cancelled) return;
        if (!bundled) {
          setLoadError(true);
          Taro.showToast({ title: copy.workUi.loadFail, icon: "none" });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [slug, skipBundled, isWeapp, title, locale, copy.workUi.loadFail]);

  const paragraphs = content ? formatParagraphs(applyLiveContacts(content, legalMeta), locale) : [];

  return (
    <PageShell title={docTitle || title} label={copy.legalUi.legalAndPrivacy} wide>
      <View className="legal-doc">
        {loading ? (
          <Text className="legal-doc__loading">{copy.legalUi.docLoading}</Text>
        ) : loadError && !paragraphs.length ? (
          <Text className="legal-doc__error">{copy.legalUi.docLoadFail}</Text>
        ) : (
          paragraphs.map((p, i) => (
            <Text key={i} className="legal-doc__para">
              {p}
            </Text>
          ))
        )}
      </View>
    </PageShell>
  );
}
