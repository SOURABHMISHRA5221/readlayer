/**
 * The problem section's illustrations (decision 44 V3): made with Gemini 3.1 Flash Image
 * (prompt landing-art-v1), white made transparent so the wash shows through; dark theme inverts
 * them in landing.css. Meaningful images, so they carry alt text.
 */
const WIDTH = 460;
const HEIGHT = 368;

interface ProblemArtProps {
  name: "jargon" | "tabs" | "shredder";
  alt: string;
}

export function ProblemArt({ name, alt }: ProblemArtProps) {
  const src = `/landing/problem-${name}.webp`;
  return (
    <img
      className="lp-problem__art"
      src={src}
      srcSet={`${src} 1x, /landing/problem-${name}@2x.webp 2x`}
      width={WIDTH}
      height={HEIGHT}
      alt={alt}
      loading="lazy"
      decoding="async"
    />
  );
}
