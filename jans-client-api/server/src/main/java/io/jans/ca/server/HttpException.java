package io.jans.ca.server;

import io.jans.ca.common.ErrorResponse;
import io.jans.ca.common.ErrorResponseCode;
import io.jans.ca.common.Jackson2;
import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.Objects;

/**
 * @author Yuriy Zabrovarnyy
 */
public class HttpException extends WebApplicationException {

    private final ErrorResponseCode code;

    public HttpException(ErrorResponseCode code) {
        super(Response.status(code.getHttpStatus()).type(MediaType.APPLICATION_JSON_TYPE).entity(Jackson2.asJsonSilently(new ErrorResponse(code))).build());
        this.code = code;
    }

    public ErrorResponseCode getCode() {
        return code;
    }

    public static HttpException internalError() {
        return new HttpException(ErrorResponseCode.INTERNAL_ERROR_UNKNOWN);
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        HttpException that = (HttpException) o;
        return code == that.code;
    }

    @Override
    public int hashCode() {

        return Objects.hash(code);
    }

    @Override
    public String toString() {
        return "HttpException{" +
                "code=" + code +
                "} " + super.toString();
    }
}
