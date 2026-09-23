package org.wwz.ai.test.domain;

import org.junit.Assert;
import org.junit.Test;
import org.wwz.ai.application.agent.featured.FeaturedConversationPublicQueryApplicationService;
import org.wwz.ai.domain.agent.ledger.ExecutionLedgerQueryService;
import org.wwz.ai.domain.agent.ledger.IFeaturedConversationRepository;
import org.wwz.ai.domain.agent.ledger.entity.FeaturedConversation;
import org.wwz.ai.domain.agent.ledger.model.ConversationHistoryDetail;
import org.wwz.ai.domain.agent.ledger.model.DialogueRunView;
import org.wwz.ai.domain.agent.ledger.model.DialogueSessionView;
import org.wwz.ai.domain.agent.ledger.model.FeaturedConversationAdminView;
import org.wwz.ai.domain.agent.ledger.model.FeaturedConversationCardView;
import org.wwz.ai.domain.agent.ledger.model.FeaturedConversationPageResult;
import org.wwz.ai.domain.agent.ledger.model.FeaturedConversationPublicDetail;
import org.wwz.ai.domain.agent.ledger.model.FeaturedConversationQueryCondition;
import org.wwz.ai.domain.agent.ledger.model.FeaturedConversationUpsertCommand;
import org.wwz.ai.domain.agent.ledger.model.ExecutionRunDetail;
import org.wwz.ai.domain.agent.ledger.model.ToolInvocationView;
import org.wwz.ai.domain.agent.ledger.replay.ConversationHistoryReplayService;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 精品对话公共查询应用服务边界回归（stub DAO / ledger / replay，不起服务）。
 * <p>
 * 钉死钳制、offset、空白 id、非 ONLINE、session_history_missing 串、空表与排序透传，
 * 与 backend-python 的 FeaturedConversationQueryUseCase 逐条对齐。
 */
public class FeaturedConversationPublicQueryApplicationServiceTest {

    private static final LocalDateTime T_1 = LocalDateTime.of(2026, 7, 6, 10, 0, 0);
    private static final LocalDateTime T_2 = LocalDateTime.of(2026, 7, 6, 11, 0, 0);
    private static final LocalDateTime T_3 = LocalDateTime.of(2026, 7, 6, 12, 0, 0);

    @Test
    public void shouldClampHomeLimitToOneAndNeverUpperBound() {
        StubContext ctx = new StubContext();
        ctx.dao.seed("featured-001", "session-001", "ONLINE", 10);
        ctx.dao.seed("featured-002", "session-002", "ONLINE", 20);

        ctx.service.queryHomeCards(0);
        Assert.assertEquals(1, ctx.dao.lastLimit);

        ctx.service.queryHomeCards(-3);
        Assert.assertEquals(1, ctx.dao.lastLimit);

        ctx.service.queryHomeCards(2);
        Assert.assertEquals(2, ctx.dao.lastLimit);

        // 无上限：原样透传，不做 min()。
        ctx.service.queryHomeCards(500);
        Assert.assertEquals(500, ctx.dao.lastLimit);
    }

    @Test
    public void shouldClampPagingAndComputeOffsetFromOneBasedPageNo() {
        StubContext ctx = new StubContext();
        ctx.dao.seed("featured-001", "session-001", "ONLINE", 10);

        FeaturedConversationPageResult<FeaturedConversationCardView> third =
                ctx.service.queryPublicList(3, 10);
        Assert.assertEquals(20, ctx.dao.lastOffset);
        Assert.assertEquals(10, ctx.dao.lastLimit);

        FeaturedConversationPageResult<FeaturedConversationCardView> clamped =
                ctx.service.queryPublicList(0, 0);
        Assert.assertEquals(0, ctx.dao.lastOffset);
        Assert.assertEquals(1, ctx.dao.lastLimit);

        FeaturedConversationPageResult<FeaturedConversationCardView> negative =
                ctx.service.queryPublicList(-5, -2);
        Assert.assertEquals(0, ctx.dao.lastOffset);
        Assert.assertEquals(1, ctx.dao.lastLimit);

        Assert.assertEquals(1, third.getTotal());
        Assert.assertEquals(1, clamped.getTotal());
        Assert.assertEquals(1, negative.getTotal());
    }

    @Test
    public void shouldReturnEmptyHomeListAndZeroTotalPageWhenTableEmpty() {
        StubContext ctx = new StubContext();

        List<FeaturedConversationCardView> home = ctx.service.queryHomeCards(6);
        Assert.assertNotNull(home);
        Assert.assertTrue(home.isEmpty());

        FeaturedConversationPageResult<FeaturedConversationCardView> page =
                ctx.service.queryPublicList(1, 20);
        Assert.assertEquals(0, page.getTotal());
        Assert.assertNotNull(page.getList());
        Assert.assertTrue(page.getList().isEmpty());
    }

    @Test
    public void shouldReturnEmptyPageWithTotalWhenOffsetPastEnd() {
        StubContext ctx = new StubContext();
        ctx.dao.seed("featured-001", "session-001", "ONLINE", 10);

        FeaturedConversationPageResult<FeaturedConversationCardView> page =
                ctx.service.queryPublicList(999, 20);

        // total 与分页无关，越界只让 list 为空。
        Assert.assertEquals(1, page.getTotal());
        Assert.assertTrue(page.getList().isEmpty());
    }

    @Test
    public void shouldPreserveDaoOrderingWithoutResorting() {
        StubContext ctx = new StubContext();
        // sort_order DESC, id DESC —— 排序是 DAO/SQL 的职责，服务层不得重排。
        ctx.dao.seed("featured-low", "session-low", "ONLINE", 10);
        ctx.dao.seed("featured-high", "session-high", "ONLINE", 30);
        ctx.dao.seed("featured-mid", "session-mid", "ONLINE", 20);

        List<FeaturedConversationCardView> home = ctx.service.queryHomeCards(6);

        Assert.assertEquals(3, home.size());
        Assert.assertEquals("featured-high", home.get(0).getFeaturedId());
        Assert.assertEquals("featured-mid", home.get(1).getFeaturedId());
        Assert.assertEquals("featured-low", home.get(2).getFeaturedId());
    }

    @Test
    public void shouldReturnNullDetailForBlankFeaturedId() {
        StubContext ctx = new StubContext();
        ctx.dao.seed("featured-001", "session-001", "ONLINE", 10);

        Assert.assertNull(ctx.service.queryDetail(null));
        Assert.assertNull(ctx.service.queryDetail(""));
        Assert.assertNull(ctx.service.queryDetail("   "));
        // 空白 id 不得触达 DAO。
        Assert.assertEquals(0, ctx.dao.queryByFeaturedIdCalls);
    }

    @Test
    public void shouldReturnNullDetailForMissingRow() {
        StubContext ctx = new StubContext();

        Assert.assertNull(ctx.service.queryDetail("featured-missing"));
    }

    @Test
    public void shouldReturnNullDetailWhenStatusIsNotOnline() {
        StubContext ctx = new StubContext();
        ctx.dao.seed("featured-offline", "session-offline", "OFFLINE", 10);
        ctx.dao.seed("featured-lower", "session-lower", "offline", 10);
        ctx.dao.seed("featured-padded", "session-padded", "  ONLINE  ", 10);
        ctx.dao.seed("featured-mixed", "session-mixed", "OnLine", 10);
        ctx.dao.seed("featured-null-status", "session-null", null, 10);

        Assert.assertNull(ctx.service.queryDetail("featured-offline"));
        // trimToEmpty + equalsIgnoreCase：大小写不敏感，两端空白被裁剪。
        Assert.assertNull(ctx.service.queryDetail("featured-lower"));
        Assert.assertNotNull(ctx.service.queryDetail("featured-padded"));
        Assert.assertNotNull(ctx.service.queryDetail("featured-mixed"));
        // null status → trimToEmpty 成空串 → 判为非 ONLINE。
        Assert.assertNull(ctx.service.queryDetail("featured-null-status"));
    }

    @Test
    public void shouldMarkHistoryMissingWhenReplayReturnsNull() {
        StubContext ctx = new StubContext();
        ctx.dao.seed("featured-001", "session-001", "ONLINE", 10);
        ctx.replay.detail = null;

        FeaturedConversationPublicDetail detail = ctx.service.queryDetail("featured-001");

        Assert.assertNotNull(detail);
        Assert.assertFalse(detail.getContentAvailable());
        Assert.assertEquals("session_history_missing", detail.getContentUnavailableReason());
        Assert.assertNull(detail.getHistoryDetail());
    }

    @Test
    public void shouldMarkContentAvailableWhenReplayReturnsDetail() {
        StubContext ctx = new StubContext();
        ctx.dao.seed("featured-001", "session-001", "ONLINE", 10);
        ctx.replay.detail = ConversationHistoryDetail.builder()
                .sessionId("session-001")
                .title("原会话")
                .build();

        FeaturedConversationPublicDetail detail = ctx.service.queryDetail("featured-001");

        Assert.assertNotNull(detail);
        Assert.assertTrue(detail.getContentAvailable());
        Assert.assertNull(detail.getContentUnavailableReason());
        Assert.assertNotNull(detail.getHistoryDetail());
    }

    @Test
    public void shouldResolveContentLastActiveAtFromLedgerSessionNotFromHistory() {
        StubContext ctx = new StubContext();
        ctx.dao.seed("featured-001", "session-001", "ONLINE", 10);
        ctx.ledger.session = DialogueSessionView.builder()
                .sessionId("session-001")
                .lastActiveAt(T_3)
                .build();
        // historyDetail 的 lastActiveAt 与卡片/详情的 contentLastActiveAt 无关。
        ctx.replay.detail = ConversationHistoryDetail.builder()
                .sessionId("session-001")
                .lastActiveAt(T_1)
                .build();

        FeaturedConversationPublicDetail detail = ctx.service.queryDetail("featured-001");
        Assert.assertEquals(T_3, detail.getContentLastActiveAt());

        List<FeaturedConversationCardView> home = ctx.service.queryHomeCards(6);
        Assert.assertEquals(T_3, home.get(0).getContentLastActiveAt());
    }

    @Test
    public void shouldEmitNullContentLastActiveAtWhenSessionMissing() {
        StubContext ctx = new StubContext();
        ctx.dao.seed("featured-blank-session", null, "ONLINE", 10);
        ctx.dao.seed("featured-orphan", "session-orphan", "ONLINE", 20);
        ctx.ledger.session = null;

        List<FeaturedConversationCardView> home = ctx.service.queryHomeCards(6);
        Assert.assertNull(home.get(0).getContentLastActiveAt());
        Assert.assertNull(home.get(1).getContentLastActiveAt());

        FeaturedConversationPublicDetail detail = ctx.service.queryDetail("featured-orphan");
        Assert.assertNull(detail.getContentLastActiveAt());
    }

    @Test
    public void shouldCarryFeaturedStatusVerbatimOnDetail() {
        StubContext ctx = new StubContext();
        ctx.dao.seed("featured-padded", "session-padded", "  ONLINE  ", 10);
        ctx.replay.detail = ConversationHistoryDetail.builder()
                .sessionId("session-padded")
                .build();

        FeaturedConversationPublicDetail detail = ctx.service.queryDetail("featured-padded");

        // detail.status 是 DB 原值，不做 trim/upper 归一。
        Assert.assertEquals("  ONLINE  ", detail.getStatus());
    }

    private static final class StubContext {
        final StubFeaturedConversationRepository dao = new StubFeaturedConversationRepository();
        final StubExecutionLedgerQueryService ledger = new StubExecutionLedgerQueryService();
        final StubConversationHistoryReplayService replay = new StubConversationHistoryReplayService();
        final FeaturedConversationPublicQueryApplicationService service =
                new FeaturedConversationPublicQueryApplicationService(dao, ledger, replay);
    }

    private static final class StubFeaturedConversationRepository
            implements IFeaturedConversationRepository {

        private final Map<String, FeaturedConversation> storage = new LinkedHashMap<>();
        int lastOffset = -1;
        int lastLimit = -1;
        int queryByFeaturedIdCalls = 0;

        void seed(String featuredId, String sessionId, String status, int sortOrder) {
            storage.put(featuredId, FeaturedConversation.builder()
                    .id((long) (storage.size() + 1))
                    .featuredId(featuredId)
                    .sessionId(sessionId)
                    .title("title-" + featuredId)
                    .summary("summary-" + featuredId)
                    .tags(List.of("研究"))
                    .sortOrder(sortOrder)
                    .status(status)
                    .publishedBy("admin")
                    .publishedAt(T_2)
                    .updatedBy("admin")
                    .updatedAt(T_2)
                    .build());
        }

        @Override
        public FeaturedConversation queryByFeaturedId(String featuredId) {
            queryByFeaturedIdCalls += 1;
            return storage.get(featuredId);
        }

        @Override
        public FeaturedConversation queryBySessionId(String sessionId) {
            return storage.values().stream()
                    .filter(item -> sessionId != null && sessionId.equals(item.getSessionId()))
                    .findFirst()
                    .orElse(null);
        }

        @Override
        public List<FeaturedConversation> queryOnlineList(int offset, int limit) {
            this.lastOffset = offset;
            this.lastLimit = limit;
            List<FeaturedConversation> online = storage.values().stream()
                    .filter(item -> item.getStatus() != null)
                    .filter(item -> "ONLINE".equalsIgnoreCase(item.getStatus().trim()))
                    .sorted(Comparator
                            .comparing(FeaturedConversation::getSortOrder,
                                    Comparator.nullsLast(Comparator.reverseOrder()))
                            .thenComparing(FeaturedConversation::getId,
                                    Comparator.nullsLast(Comparator.reverseOrder())))
                    .toList();
            if (offset >= online.size()) {
                return new ArrayList<>();
            }
            return new ArrayList<>(online.subList(offset, Math.min(offset + limit, online.size())));
        }

        @Override
        public int countOnline() {
            return (int) storage.values().stream()
                    .filter(item -> item.getStatus() != null)
                    .filter(item -> "ONLINE".equalsIgnoreCase(item.getStatus().trim()))
                    .count();
        }

        @Override
        public FeaturedConversationPageResult<FeaturedConversationAdminView> queryAdminList(
                FeaturedConversationQueryCondition condition
        ) {
            return FeaturedConversationPageResult.<FeaturedConversationAdminView>builder()
                    .total(0)
                    .list(List.of())
                    .build();
        }

        @Override
        public boolean upsert(FeaturedConversationUpsertCommand command) {
            return false;
        }

        @Override
        public boolean updateStatus(String featuredId, String status, String operator) {
            return false;
        }
    }

    private static final class StubExecutionLedgerQueryService implements ExecutionLedgerQueryService {

        DialogueSessionView session;

        @Override
        public ExecutionRunDetail queryRunDetail(String requestId) {
            return null;
        }

        @Override
        public List<ToolInvocationView> queryRecentToolInvocations(String toolName, int limit) {
            return List.of();
        }

        @Override
        public List<DialogueRunView> queryRecentSessionRuns(String sessionId, int limit) {
            return List.of();
        }

        @Override
        public List<DialogueRunView> querySessionRuns(String sessionId) {
            return List.of();
        }

        @Override
        public DialogueSessionView querySession(String sessionId) {
            return session;
        }

        @Override
        public List<DialogueSessionView> queryRecentSessions(int limit) {
            return List.of();
        }

        @Override
        public DialogueSessionView querySession(String visitorId, String sessionId) {
            return session;
        }

        @Override
        public List<DialogueSessionView> queryRecentSessions(String visitorId, int limit) {
            return List.of();
        }
    }

    private static final class StubConversationHistoryReplayService
            extends ConversationHistoryReplayService {

        ConversationHistoryDetail detail;
        String lastSessionId;

        StubConversationHistoryReplayService() {
            super(null, null, null, null);
        }

        @Override
        public ConversationHistoryDetail queryConversationHistory(String sessionId) {
            this.lastSessionId = sessionId;
            return detail;
        }
    }
}
