/** Geometric AN monogram and letterforms based on the supplied brand references. */
export function Brand({ href = '#/' }: { href?: string }) {
  return (
    <a className="brand" href={href} aria-label="AKI NATOR home">
      <img
        className="brand-mark"
        src={`${import.meta.env.BASE_URL}aki-nator-mark.svg`}
        alt=""
        width={46}
        height={24}
      />
      <img
        className="brand-wordmark"
        src={`${import.meta.env.BASE_URL}aki-nator-wordmark.svg`}
        width={132}
        height={17}
        alt="AKI NATOR"
      />
    </a>
  );
}
