/**
 * A sample brief, built to the writer's real output contract:
 * header line, themes in Title Case, per theme footnotes that reset at [1],
 * mandatory hypothesis check lines, a Highlights section, then the footer.
 *
 * The story text is illustrative. It is not real reporting, and the page says so.
 */

export interface BriefArticle {
  n: number;
  title: string;
  source: string;
  url: string;
}

export interface BriefTheme {
  bundle: string;
  title: string;
  paragraphs: string[];
  hypothesisCheck?: {
    topic: string;
    stance: string;
    verdict: "aligns with" | "challenges";
    ref: number;
  };
  coverageWarning?: string;
  articles: BriefArticle[];
}

export interface BriefHighlight {
  title: string;
  summary: string;
  source: string;
  url: string;
}

export const SAMPLE_BRIEF = {
  date: "Tuesday 5 August 2026",
  slot: "Morning brief",
  totals: {
    fetched: 612,
    scored: 154,
    passedCutoff: 41,
    themes: 9,
    highlights: 8,
  },
  themes: [
    {
      bundle: "pakistan",
      title: "Remittance Corridors Shift as Fee Pressure Builds",
      paragraphs: [
        "Two Pakistani outlets covered the same set of central bank figures from opposite ends. The formal channel is reported as growing in absolute terms while its share of total inflows slips, which is the distinction that matters for anyone watching informal rails [1][2].",
        "The second report adds the detail the first leaves out: the fee spread between the formal channel and the informal one has not narrowed, which is the mechanism behind the share loss rather than any change in diaspora behaviour [2].",
      ],
      hypothesisCheck: {
        topic:
          "Stablecoin rails will carry more remittance volume into Pakistan than the formal banking channel by 2028",
        stance: "bullish",
        verdict: "aligns with",
        ref: 2,
      },
      articles: [
        {
          n: 1,
          title: "Central bank publishes quarterly remittance breakdown",
          source: "Dawn",
          url: "https://dawn.com",
        },
        {
          n: 2,
          title: "Fee spread holds steady despite policy push, analysts say",
          source: "The Express Tribune",
          url: "https://tribune.com.pk",
        },
      ],
    },
    {
      bundle: "cybersecurity",
      title: "Surveillance Vendor Resurfaces Under New Corporate Name",
      paragraphs: [
        "A research group traced infrastructure from a previously named vendor to a newly registered entity, using overlapping certificate fingerprints rather than corporate filings [1]. Two security outlets picked the finding up the same day with no independent confirmation of their own [2][3].",
        "The method is the story. Attribution here rests on infrastructure reuse, which is strong evidence of continuity and weak evidence of ownership, and the research writeup is explicit about that limit [1].",
      ],
      hypothesisCheck: {
        topic:
          "Commercial spyware vendors keep operating through rebranded shells faster than export controls can name them",
        stance: "bearish",
        verdict: "aligns with",
        ref: 1,
      },
      articles: [
        {
          n: 1,
          title: "Infrastructure overlap links two vendor entities",
          source: "Citizen Lab",
          url: "https://citizenlab.ca",
        },
        {
          n: 2,
          title: "Researchers report continuity in vendor tooling",
          source: "The Hacker News",
          url: "https://thehackernews.com",
        },
        {
          n: 3,
          title: "Security teams advised to review indicator lists",
          source: "BleepingComputer",
          url: "https://www.bleepingcomputer.com",
        },
      ],
    },
    {
      bundle: "geopolitics",
      title: "Ceasefire Talks Enter a Second Week Without a Text",
      paragraphs: [
        "Three wires ran the same procedural update from the same briefing. The one substantive difference between them is whether a draft text exists at all, which two describe as circulating and one describes as not yet drafted [1][2][3].",
        "Nothing in any of the three reports names a signatory or a date, so the practical position is unchanged from last week despite the volume of coverage.",
      ],
      coverageWarning:
        "Left-leaning media only. Opposing view absent from today's pool.",
      articles: [
        {
          n: 1,
          title: "Negotiators meet for a fourth session",
          source: "Reuters",
          url: "https://reuters.com",
        },
        {
          n: 2,
          title: "Mediators describe progress on sequencing",
          source: "Al Jazeera",
          url: "https://aljazeera.com",
        },
        {
          n: 3,
          title: "Talks continue with no announced timeline",
          source: "The Guardian",
          url: "https://www.theguardian.com",
        },
      ],
    },
    {
      bundle: "vc",
      title: "One Essay on Seed Pricing Stands Alone This Week",
      paragraphs: [
        "A single long form piece argues that seed round pricing has decoupled from the quality of the underlying team, and supports it with a cohort comparison rather than anecdote [1]. Venture runs on a seven day window in this pipeline precisely so a piece like this is not lost to a quiet Tuesday.",
      ],
      hypothesisCheck: {
        topic:
          "Small teams shipping with AI agents will take real share from mid size software vendors",
        stance: "bullish",
        verdict: "challenges",
        ref: 1,
      },
      articles: [
        {
          n: 1,
          title: "What seed pricing stopped measuring",
          source: "The Generalist",
          url: "https://generalist.com",
        },
      ],
    },
  ] satisfies BriefTheme[],
  whatChanged: [
    {
      thread: "quarterly remittance total",
      note: "was $2.9B on 2 Aug, now $3.1B (+6.9%)",
    },
    {
      thread: "named vendor entities",
      note: "was 4 tracked, now 5",
    },
  ],
  investigations: [
    {
      slug: "port-logistics",
      source: "Bellingcat",
      url: "https://www.bellingcat.com",
      summary:
        "An open source review of vessel tracking and port imagery documents a shipping route that does not appear in the operator's published schedules. Reply with more: port-logistics for the full write up.",
    },
  ],
  blindspot: {
    headline: "A regional water agreement passed with almost no coverage",
    note: "Covered by 6 outlets, all centre and right. Left-leaning outlets did not run it.",
    url: "https://ground.news/blindspot",
  },
  highlights: [
    {
      title: "Regulator Opens Consultation on Stablecoin Reserve Rules",
      summary:
        "A ninety day comment window opens on reserve composition and attestation frequency. No draft rule text was published alongside it.",
      source: "The Block",
      url: "https://theblock.co",
    },
    {
      title: "Undersea Cable Repair Ship Reaches the Break Site",
      summary:
        "Repair is expected to take under a week. Traffic has been rerouted since the outage began.",
      source: "Ars Technica",
      url: "https://arstechnica.com",
    },
    {
      title: "Two Research Labs Publish Conflicting Benchmark Results",
      summary:
        "The disagreement traces to different evaluation harnesses rather than different models. Both released their harness code.",
      source: "MIT Technology Review",
      url: "https://technologyreview.com",
    },
    {
      title: "Court Filing Names Three Data Brokers in Location Case",
      summary:
        "The filing is a complaint, not a finding. No response has been entered yet.",
      source: "The Intercept",
      url: "https://theintercept.com",
    },
    {
      title: "Fund Closes Second Vehicle Below Its Stated Target",
      summary:
        "The final close came in under target after a fourteen month raise. Strategy is unchanged from the first fund.",
      source: "Not Boring",
      url: "https://notboring.co",
    },
    {
      title: "Provincial Budget Moves Development Spending to Q4",
      summary:
        "The reallocation is procedural. Total spending is unchanged for the year.",
      source: "The News International",
      url: "https://www.thenews.com.pk",
    },
    {
      title: "Ransomware Group Publishes a Partial Victim List",
      summary:
        "Two named organisations have confirmed contact. The rest are unverified.",
      source: "Dark Reading",
      url: "https://www.darkreading.com",
    },
    {
      title: "Essay Argues Distribution Now Beats Model Quality",
      summary:
        "The argument rests on switching costs rather than benchmark scores. No new data is presented.",
      source: "Stratechery",
      url: "https://stratechery.com",
    },
  ] satisfies BriefHighlight[],
};
