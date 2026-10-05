package dev.factory.operations.stream;

import java.io.IOException;
import java.util.UUID;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.dao.DataAccessException;
import dev.factory.operations.api.ApiProblem;
import dev.factory.operations.domain.*;
import static dev.factory.operations.domain.ReadSupport.map;

/** Only the contracted /stream route bypasses MVC to use Servlet non-blocking output. */
@Component
@Profile("!bootstrap")
public class StreamFilter extends OncePerRequestFilter {
    private final SnapshotStreams streams;
    public StreamFilter(SnapshotStreams streams){this.streams=streams;}
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain) throws ServletException,IOException {
        String path=request.getRequestURI();
        if(!path.matches("/api/v1/runs/[^/]+/stream")){chain.doFilter(request,response);return;}
        try {
            if(!request.getMethod().equals("GET"))throw new ApiProblem(405,"METHOD_NOT_ALLOWED");
            String run=path.substring("/api/v1/runs/".length(),path.length()-"/stream".length());HistoryQueries.runId(run);
            if(!request.getParameterMap().isEmpty())throw new ApiProblem(400,"INVALID_QUERY");
            streams.open(run,request,response);
        }catch(ApiProblem p){error(response,p.http,p.code);}
        catch(DataAccessException unavailable){error(response,503,"DB_UNAVAILABLE");}
        catch(RuntimeException unavailable){error(response,503,"VIEW_NOT_READY");}
    }
    private void error(HttpServletResponse response,int status,String code) throws IOException {
        if(response.isCommitted())return;response.setStatus(status);response.setContentType("application/json");response.setCharacterEncoding("UTF-8");response.setHeader("Cache-Control","no-store");if(status==429)response.setHeader("Retry-After","2");
        response.getOutputStream().write(EventSyntax.JSON.writeValueAsBytes(map("schemaVersion",1,"code",code,"message",status==429?"화면 연결 수가 가득 찼습니다. 잠시 뒤 다시 연결하세요.":"관제 연결과 실행 정보를 확인하세요.","requestId",UUID.randomUUID().toString())));
    }
}
