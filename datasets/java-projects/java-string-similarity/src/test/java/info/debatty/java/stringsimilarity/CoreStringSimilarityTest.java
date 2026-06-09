package info.debatty.java.stringsimilarity;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public class CoreStringSimilarityTest {

    private static final double EPSILON = 0.000001;

    @Test
    public void levenshteinComputesEditDistance() {
        Levenshtein distance = new Levenshtein();

        assertEquals(0.0, distance.distance("book", "book"), EPSILON);
        assertEquals(3.0, distance.distance("kitten", "sitting"), EPSILON);
        assertEquals(4.0, distance.distance("", "test"), EPSILON);
    }

    @Test
    public void normalizedLevenshteinComputesDistanceAndSimilarity() {
        NormalizedLevenshtein metric = new NormalizedLevenshtein();

        assertEquals(0.0, metric.distance("task", "task"), EPSILON);
        assertEquals(0.25, metric.distance("task", "mask"), EPSILON);
        assertEquals(0.75, metric.similarity("task", "mask"), EPSILON);
    }

    @Test
    public void lcsComputesSubsequenceLengthAndDistance() {
        LongestCommonSubsequence lcs = new LongestCommonSubsequence();

        assertEquals(4, lcs.length("AGGTAB", "GXTXAYB"));
        assertEquals(5.0, lcs.distance("AGGTAB", "GXTXAYB"), EPSILON);
    }

    @Test
    public void metricLcsNormalizesTheCommonSubsequenceScore() {
        MetricLCS metric = new MetricLCS();

        assertEquals(0.0, metric.distance("abc", "abc"), EPSILON);
        assertEquals(1.0 - 4.0 / 7.0, metric.distance("AGGTAB", "GXTXAYB"), EPSILON);
    }

    @Test
    public void ngramDistanceHandlesExactAndDifferentStrings() {
        NGram ngram = new NGram(2);

        assertEquals(0.0, ngram.distance("context", "context"), EPSILON);
        assertEquals(1.0, ngram.distance("", "context"), EPSILON);
    }

    @Test(expected = NullPointerException.class)
    public void levenshteinRejectsNullInput() {
        new Levenshtein().distance(null, "value");
    }
}
